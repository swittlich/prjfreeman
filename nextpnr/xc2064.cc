// SPDX-License-Identifier: ISC
// Copyright (C) 2026 Sebastian Wittlich
/*
 *  nextpnr-himbaechel uarch "xc2064": model of the Xilinx XC2064 (1985, the first FPGA).
 *  Fabric description: xc2064_arch_gen.py.
 *
 *  Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee
 *  is hereby granted, provided that the above copyright notice and this permission notice appear in all
 *  copies. See the file LICENSE.
 */

#include <algorithm>
#include <array>
#include <fstream>
#include <set>
#include <sstream>

#include "himbaechel_api.h"
#include "log.h"
#include "nextpnr.h"
#include "util.h"

#include "himbaechel_helpers.h"

#define GEN_INIT_CONSTIDS
#define HIMBAECHEL_CONSTIDS "uarch/xc2064/constids.inc"
#define HIMBAECHEL_GFXIDS "uarch/xc2064/gfxids.inc"
#define HIMBAECHEL_UARCH xc2064
#include "himbaechel_constids.h"
#include "himbaechel_gfxids.h"

NEXTPNR_NAMESPACE_BEGIN

namespace {

// z positions of the Bels of a CLB tile (see xc2064_arch_gen.py)
enum ClbZ
{
    Z_F = 0,  // LUT3: function F of 3 variables
    Z_G = 1,  // LUT3: function G of 3 variables
    Z_FG = 2,  // LUT4: F and G as one function of 4 variables
    Z_FF = 3,  // DFF: flip-flop or latch
    Z_FGM = 4, // FGM: F and G with their own inputs, B selects (mux mode)
};

// Signal sources inside a CLB (for the assignment of the input multiplexers)
enum Src
{
    S_A = 0, // CLB inputs A-D: each carries exactly one net
    S_B,
    S_C,
    S_D,
    S_Q, // FF output of this CLB
    S_F, // output F or FG/FGM of this CLB
    S_G, // output G or FG/FGM of this CLB
    S_K, // clock input K (global clock nets only)
    S_COUNT
};
constexpr uint8_t M(Src s) { return uint8_t(1u << s); }

// Input multiplexers according to Shirriff's bitstream decoder (clb.js)
constexpr uint8_t LUT_IN_OPTS[4] = {
        M(S_A) | M(S_B),          // input 1 from A or B
        M(S_B) | M(S_C),          // input 2 from B or C
        M(S_C) | M(S_D) | M(S_Q), // input 3 from C, D or Q
        M(S_B),                   // FG and FGM: B selects between F and G
};

constexpr uint8_t FF_CLK_OPTS = M(S_K) | M(S_C) | M(S_G);
constexpr uint8_t FF_SET_OPTS = M(S_A) | M(S_F);
constexpr uint8_t FF_RES_OPTS = M(S_D) | M(S_G);

// Extra data of a pip from the graph (xc2064_arch_gen.py, PipExtra): the line in the text format that programs it,
// and its kind
NPNR_PACKED_STRUCT(struct Xc2064PipExtraPOD {
    int32_t cfg;  // IdString of the text line
    int32_t kind; // PIP_CFG or PIP_CLKBUF
});
enum PipKind
{
    PIP_CFG = 1,
    PIP_CLKBUF = 2, // input of a clock buffer: blocked with --vopt noclkbuf
};

// The two clock buffers and the pads their input mux can select directly (codes from MAKEBITS)
constexpr const char *CLOCK_BUFFERS[2] = {"GCLK", "ACLK"};
constexpr const char *CLOCK_PADS[2][2] = {{"P9", "P11"}, {"P43", "P46"}};

struct Xc2064Impl : HimbaechelAPI
{
    ~Xc2064Impl() {};

    po::options_description getUArchOptions()
    {
        po::options_description specific("XC2064 specific options");
        specific.add_options()("pcf", po::value<std::string>(),
                               "PCF file with pin constraints: set_io [-nowarn] <port> <pin> (pins of the package, "
                               "e.g. P9)");
        specific.add_options()("package", po::value<std::string>(),
                               "package: PC68 (default, 58 I/O), PD48 (40 I/O), PC44 (34 I/O) or PG68 (57 I/O, pins "
                               "A2...L10)");
        specific.add_options()("out", po::value<std::string>(),
                               "write the configuration as text for xc2064pack (format: arch/xc2064/xc2064db/config.py)");
        specific.add_options()("noclkbuf", "do not use the clock buffers GCLK/ACLK: clocks run over the general "
                                           "routing like any other signal");
        specific.add_options()("clkbuf", "use the clock buffers GCLK (pads P9, P11) and ACLK (P43, P46), the default: "
                                         "clocks at these pads run over them, clocks without a pin constraint are "
                                         "placed there");
        return specific;
    }

    // Speed grade from the device name as with Xilinx: XC2064-50, -70, -100, -130 (toggle rate in MHz); no suffix
    // means -70
    void init_database(Arch *arch) override
    {
        init_uarch_constids(arch);
        arch->load_chipdb("xc2064/chipdb-xc2064.bin");
        const std::string &dev = arch->args.device;
        auto dash = dev.find('-');
        arch->set_speed_grade(dash == std::string::npos ? "70" : dev.substr(dash + 1));
        // Package (xc2064db/packages.py): the IOB Bels are named after the PLCC68 pin, PCF and LOC name the pin of
        // the selected package
        auto pkg = arch->args.options.find("package");
        package = pkg == arch->args.options.end() ? "PC68" : pkg->second.as<std::string>();
        if (package != "PC68" && package != "PD48" && package != "PC44" && package != "PG68")
            log_error("Unknown package '%s' (PC68, PD48, PC44 or PG68)\n", package.c_str());
        arch->set_package(package);
    }

    void init(Context *ctx) override
    {
        h.init(ctx);
        HimbaechelAPI::init(ctx);
        // Pads by package pin, the bonded IOBs and the pads of the clock buffers (Bel names P9 and P11 for GCLK,
        // P43 and P46 for ACLK)
        for (BelId bel : ctx->getBels()) {
            if (ctx->getBelType(bel) != id_IOB)
                continue;
            if (const PadInfoPOD *pad = ctx->get_bel_package_pin(bel)) {
                pad_bels[IdString(pad->package_pin)] = bel;
                bonded.insert(bel);
            }
            side_iobs[side_index(io_side(ctx->getBelLocation(bel)))].push_back(bel);
            IdString name = ctx->getBelName(bel)[1];
            for (int b = 0; b < 2; b++)
                for (int i = 0; i < 2; i++)
                    if (name == ctx->id(CLOCK_PADS[b][i]))
                        clock_pads[b][i] = bel;
        }
        // Clock buffers: on by default, --vopt noclkbuf turns them off (--vopt clkbuf remains allowed)
        clkbuf = ctx->args.options.count("noclkbuf") == 0;
        if (!clkbuf && ctx->args.options.count("clkbuf"))
            log_error("--vopt clkbuf and --vopt noclkbuf are mutually exclusive\n");
    }

    // The routing of the XC2064 is scarce (4 tracks per channel, 81 crossings): router2 resolves congestion more
    // reliably than router1 (as with gatemate/xilinx). "--router router1" remains possible.
    std::string getDefaultRouter() const override { return "router2"; }

    // IO buffers (all on one IOB): input, latched input, output, tristate output, bidirectional
    static bool is_io_buffer(IdString type)
    {
        return type.in(id_XC2000_INBUF, id_XC2000_INFF, id_XC2000_OUTBUF, id_XC2000_TOBUF, id_XC2000_IOBUF);
    }

    // IO buffer whose PAD is connected to the top-level port (cell $nextpnr_*buf)
    static CellInfo *io_buffer(CellInfo *port)
    {
        auto is_buf = [](const PortRef &r) { return r.cell && is_io_buffer(r.cell->type) && r.port == id_PAD; };
        for (auto &p : port->ports) {
            NetInfo *net = p.second.net;
            if (!net)
                continue;
            if (is_buf(net->driver))
                return net->driver.cell;
            for (auto &u : net->users)
                if (is_buf(u))
                    return u.cell;
        }
        return nullptr;
    }

    // Pin assignment from a PCF file as with iCE40: "set_io [-nowarn] <port> <pin>", buses as name[i]. Sets LOC on
    // the IO buffer of the port, overriding any LOC from the Verilog.
    void read_pcf(const std::string &file)
    {
        std::ifstream in(file);
        if (!in)
            log_error("Cannot read PCF file '%s'\n", file.c_str());
        log_info("Reading pin assignment from %s\n", file.c_str());
        dict<IdString, std::string> used; // pin -> port
        std::string line;
        for (int lineno = 1; std::getline(in, line); lineno++) {
            std::istringstream ss(line.substr(0, line.find('#')));
            std::vector<std::string> w;
            for (std::string t; ss >> t;)
                w.push_back(t);
            if (w.empty())
                continue;
            if (w[0] != "set_io")
                log_error("%s:%d: unknown command '%s' (only set_io)\n", file.c_str(), lineno, w[0].c_str());
            bool nowarn = false;
            size_t i = 1;
            for (; i < w.size() && w[i][0] == '-'; i++) {
                if (w[i] == "-nowarn")
                    nowarn = true;
                else
                    log_warning("%s:%d: option '%s' is ignored\n", file.c_str(), lineno, w[i].c_str());
            }
            if (i + 2 != w.size())
                log_error("%s:%d: expected 'set_io [-nowarn] <port> <pin>'\n", file.c_str(), lineno);
            const std::string &port_name = w[i], &pin_name = w[i + 1];
            IdString pin = ctx->id(pin_name);
            if (!pad_bels.count(pin))
                log_error("%s:%d: '%s' is not an I/O pin of package %s\n", file.c_str(), lineno, pin_name.c_str(),
                          package.c_str());
            if (used.count(pin))
                log_error("%s:%d: pin %s is already assigned to '%s'\n", file.c_str(), lineno, pin_name.c_str(),
                          used.at(pin).c_str());
            CellInfo *port = ctx->getCellForPinConstraint(port_name);
            if (!port) {
                if (!nowarn)
                    log_warning("%s:%d: no port '%s' in the design\n", file.c_str(), lineno, port_name.c_str());
                continue;
            }
            CellInfo *buf = io_buffer(port);
            if (!buf)
                log_error("%s:%d: port '%s' has no IO buffer XC2000_*BUF (synth_xc2064 -noiopad?)\n",
                          file.c_str(), lineno, port_name.c_str());
            auto old = buf->attrs.find(id_LOC);
            if (old != buf->attrs.end() && old->second.as_string() != pin_name)
                log_warning("%s:%d: '%s' was at %s via LOC, now at %s\n", file.c_str(), lineno,
                            port_name.c_str(), old->second.as_string().c_str(), pin_name.c_str());
            buf->attrs[id_LOC] = pin_name;
            used[pin] = port_name;
            log_info("    %s -> %s\n", port_name.c_str(), pin_name.c_str());
        }
    }

    // Pins from the PCF or (* LOC="P9" *) on the IO buffer (XC2000_INBUF etc.): bind the IOB firmly already while
    // packing (like GateMate), so that the GUI shows the occupied pads after "Pack". Any BEL attribute is dropped,
    // otherwise the placer would try to bind the cell a second time.
    void bind_constrained_pads()
    {
        int bound = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            auto loc = ci->attrs.find(id_LOC);
            if (!is_io_buffer(ci->type) || loc == ci->attrs.end())
                continue;
            IdString pin = ctx->id(loc->second.as_string());
            if (!pad_bels.count(pin))
                log_error("%s: LOC \"%s\" is not an I/O pin of package %s\n", ci->name.c_str(ctx), pin.c_str(ctx),
                          package.c_str());
            BelId bel = pad_bels.at(pin);
            if (!ctx->checkBelAvail(bel))
                log_error("%s: pad %s is already occupied by %s\n", ci->name.c_str(ctx), pin.c_str(ctx),
                          ctx->nameOf(ctx->getBoundBelCell(bel)));
            ci->attrs.erase(id_BEL);
            ctx->bindBel(bel, ci, STRENGTH_FIXED);
            bound++;
        }
        log_info("Placed %d IO buffers at their constrained pads.\n", bound);
    }

    // Clocks without a pin assignment go to the clock pads: only via the clock buffers GCLK (pads P9, P11) and ACLK
    // (P43, P46) does a clock reach K of all CLBs, otherwise it occupies one of the inputs A-D in every CLB. Each
    // buffer takes one net: the one with the most storage elements gets GCLK, the next one ACLK, each at the first
    // free pad. If a clock is already constrained to a pad of a buffer, the buffer stays with that clock.
    void bind_clock_pads()
    {
        dict<IdString, int> clk_users; // net -> number of storage elements
        for (auto &cell : ctx->cells) {
            const CellInfo *ci = cell.second.get();
            const NetInfo *clk = ci->type == id_XC2000_DFF ? ci->getPort(id_CLK) : nullptr;
            if (clk)
                clk_users[clk->name]++;
        }
        std::array<bool, 2> taken{};
        std::vector<std::pair<int, NetInfo *>> clocks;
        for (auto &u : clk_users) {
            NetInfo *net = ctx->nets.at(u.first).get();
            const CellInfo *drv = net->driver.cell;
            if (!is_pad_input(net))
                continue; // derived clock: runs over the general routing
            if (drv->bel != BelId() || drv->attrs.count(id_BEL)) {
                int b = clock_buffer(net);
                if (b < 0)
                    log_info("Clock '%s' (%s) is constrained to a pad without clock buffer, uses CLB inputs.\n",
                             ctx->nameOf(net), storage_elements(u.second).c_str());
                else
                    taken[b] = true;
                continue;
            }
            clocks.push_back({u.second, net});
        }
        std::stable_sort(clocks.begin(), clocks.end(),
                         [](const auto &a, const auto &b) { return a.first > b.first; });
        auto next = clocks.begin();
        for (int b = 0; b < 2 && next != clocks.end(); b++) {
            if (taken[b])
                continue;
            for (BelId pad : clock_pads[b]) {
                if (pad == BelId() || !ctx->checkBelAvail(pad) || !bonded.count(pad))
                    continue;
                ctx->bindBel(pad, next->second->driver.cell, STRENGTH_FIXED);
                log_info("Clock '%s' (%s) placed at %s (%s).\n", ctx->nameOf(next->second),
                         storage_elements(next->first).c_str(), ctx->getBelName(pad)[1].c_str(ctx),
                         CLOCK_BUFFERS[b]);
                ++next;
                break;
            }
        }
        for (; next != clocks.end(); ++next)
            log_info("Clock '%s' (%s): no free clock buffer, uses CLB inputs.\n", ctx->nameOf(next->second),
                     storage_elements(next->first).c_str());
    }

    // In the original, a constant T is not a signal but the mode of the IOB (T mux "on" or "off", iob.js): the
    // routing graph has no pips for it. T = 0 (driver always on) becomes XC2000_OUTBUF; for an XC2000_IOBUF the
    // users of O then read I directly. T = 1 (driver off) becomes XC2000_INBUF; for an XC2000_TOBUF the pad thus
    // remains an input without users.
    void fold_constant_tristate()
    {
        int on = 0, off = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (!ci->type.in(id_XC2000_TOBUF, id_XC2000_IOBUF))
                continue;
            NetInfo *t = ci->getPort(id_T);
            const CellInfo *drv = t ? t->driver.cell : nullptr;
            if (!drv || !drv->type.in(id_GND, id_VCC))
                continue;
            bool always_on = drv->type == id_GND;
            ci->disconnectPort(id_T);
            ci->ports.erase(id_T);
            if (always_on) {
                NetInfo *i = ci->getPort(id_I), *o = ci->getPort(id_O);
                if (o) {
                    if (!i)
                        log_error("%s: tristate buffer with T = 0 but without input I\n", ctx->nameOf(ci));
                    std::vector<PortRef> users;
                    for (auto &u : o->users)
                        users.push_back(u);
                    for (auto &u : users) {
                        u.cell->disconnectPort(u.port);
                        u.cell->connectPort(u.port, i);
                    }
                    ci->disconnectPort(id_O);
                    ci->ports.erase(id_O);
                }
                ci->type = id_XC2000_OUTBUF;
                on++;
            } else {
                ci->disconnectPort(id_I);
                ci->ports.erase(id_I);
                if (!ci->ports.count(id_O))
                    ci->addOutput(id_O);
                ci->type = id_XC2000_INBUF;
                off++;
            }
        }
        if (on || off)
            log_info("Tristate buffers with constant T: %d always driving (OUTBUF), %d never driving (INBUF).\n", on,
                     off);
    }

    // Constants: the XC2064 has no constant line. A constant LUT input is folded into the LUT contents (INIT then
    // no longer depends on it, its input mux stays off), set/reset = 0 means no set/reset, an FGM with a fixed S
    // becomes the selected table as a LUT3. Whatever remains (constant output of a pad, set/reset = 1, clock, ...)
    // is driven by a LUT with constant contents, one per value; an FF data input gets its own (D only from F/FG of
    // the CLB).
    void fold_constants()
    {
        int folded = 0, dropped = 0, luts = 0;
        std::vector<std::pair<CellInfo *, int>> fixed_select; // FGM with fixed S
        std::vector<IdString> drivers;
        dict<int, NetInfo *> const_net; // 0/1 -> net of the shared constant LUT
        auto const_lut = [&](int value, IdString name) {
            CellInfo *lut = ctx->createCell(name, id_XC2000_LUT3);
            for (int i = 0; i < 3; i++)
                lut->addInput(lut_in(i));
            lut->addOutput(id_O);
            lut->params[id_INIT] = Property(value ? 0xFF : 0, 8);
            NetInfo *net = ctx->createNet(ctx->idf("%s$O", name.c_str(ctx)));
            lut->connectPort(id_O, net);
            luts++;
            return net;
        };
        std::vector<NetInfo *> nets; // collect first: const_lut creates nets
        for (auto &n : ctx->nets) {
            const CellInfo *drv = n.second->driver.cell;
            if (drv && drv->type.in(id_GND, id_VCC))
                nets.push_back(n.second.get());
        }
        for (NetInfo *net : nets) {
            const CellInfo *drv = net->driver.cell;
            drivers.push_back(drv->name);
            int value = drv->type == id_VCC;
            std::vector<PortRef> users;
            for (auto &u : net->users)
                users.push_back(u);
            for (auto &u : users) {
                CellInfo *ci = u.cell;
                const Table *table = nullptr;
                int idx = -1;
                auto ts = tables(ci);
                for (const Table &t : ts)
                    for (int i = 0; i < t.width(); i++)
                        if (u.port == t.ports[i])
                            table = &t, idx = i;
                ci->disconnectPort(u.port);
                if (table) { // LUT input: copy the contents for the fixed value to all addresses
                    set_init(ci, *table, fold_input(init_of(ci, *table), table->width(), idx, value));
                    folded++;
                } else if (ci->type == id_XC2000_FGM && u.port == id_S) {
                    fixed_select.push_back({ci, value});
                } else if (ci->type == id_XC2000_DFF && u.port.in(id_S, id_R) && value == 0) {
                    dropped++;
                } else if (ci->type == id_XC2000_DFF && u.port == id_D) {
                    ci->connectPort(u.port, const_lut(value, ctx->idf("$xc2064_const%d$%s", value, ci->name.c_str(ctx))));
                } else {
                    if (!const_net.count(value))
                        const_net[value] = const_lut(value, ctx->idf("$xc2064_const%d", value));
                    ci->connectPort(u.port, const_net.at(value));
                }
            }
        }
        for (IdString name : drivers) {
            CellInfo *drv = ctx->cells.at(name).get();
            for (auto &p : drv->ports)
                if (p.second.net)
                    ctx->nets.erase(p.second.net->name);
            ctx->cells.erase(name);
        }
        for (auto &fs : fixed_select)
            fgm_to_lut3(fs.first, fs.second);
        if (folded || dropped || luts || !fixed_select.empty())
            log_info("Constants: %d LUT inputs folded into INIT, %d set/reset inputs dropped, %d constant LUTs, %d FGM "
                     "with fixed select.\n",
                     folded, dropped, luts, int(fixed_select.size()));
    }

    // FGM with fixed S: only the selected table remains (S = 1: F, S = 0: G), as a LUT3 with its inputs
    void fgm_to_lut3(CellInfo *ci, int s)
    {
        int keep = s ? 0 : 1;
        uint64_t init = uint64_t(ci->params.at(keep ? id_INIT_G : id_INIT_F).as_int64());
        for (int h = 0; h < 2; h++)
            for (int i = 0; i < 3; i++) {
                IdString p = fgm_in(h, i);
                NetInfo *net = ci->getPort(p);
                ci->disconnectPort(p);
                ci->ports.erase(p);
                if (h == keep) {
                    ci->addInput(lut_in(i));
                    if (net)
                        ci->connectPort(lut_in(i), net);
                }
            }
        ci->ports.erase(id_S);
        ci->params.erase(id_INIT_F);
        ci->params.erase(id_INIT_G);
        ci->params[id_INIT] = Property(int64_t(init), 8);
        ci->type = id_XC2000_LUT3;
    }

    static std::string storage_elements(int n)
    {
        return std::to_string(n) + (n == 1 ? " storage element" : " storage elements");
    }

    void pack() override
    {
        if (ctx->args.options.count("pcf"))
            read_pcf(ctx->args.options.at("pcf").as<std::string>());
        // IO buffers are inserted by synthesis (synth_xc2064)
        const pool<CellTypePort> top_ports{
                CellTypePort(id_XC2000_INBUF, id_PAD),
                CellTypePort(id_XC2000_INFF, id_PAD),
                CellTypePort(id_XC2000_OUTBUF, id_PAD),
                CellTypePort(id_XC2000_TOBUF, id_PAD),
                CellTypePort(id_XC2000_IOBUF, id_PAD),
        };
        h.remove_nextpnr_iobs(top_ports);
        fold_constant_tristate();
        fold_constants();
        bind_constrained_pads();
        check_iob_clocks();
        if (clkbuf_enabled())
            bind_clock_pads();
        int moved = route_q_feedback_to_i2();
        int unused = fold_unused_lut_inputs();
        // The FF gets its data only from F or FG/FGM of the same CLB. synth_xc2064 ensures that every FF has its
        // own LUT; LUT and FF are placed together here as a cluster.
        const pool<CellTypePort> ff_d{{id_XC2000_DFF, id_D}};
        int n3 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT3, id_O}}, ff_d, Z_FF - Z_F);
        int n4 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT4, id_O}}, ff_d, Z_FF - Z_FG);
        int nm = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_FGM, id_O}}, ff_d, Z_FF - Z_FGM);
        log_info("Constrained %d LUT3/FF, %d LUT4/FF and %d FGM/FF pairs, %d Q feedback inputs moved to input 3, "
                 "%d unused LUT inputs made don't-care.\n",
                 n3, n4, nm, moved, unused);
        pair_lut3();
        dff_timing();
    }

    // CLB pairs: if the design has more LUT cells than the chip has CLBs, pack() puts LUT3s in pairs as F and G
    // into one CLB. Otherwise the placer (HeAP) spreads them individually over the chip, and no room is left for
    // LUT4 and FGM, which need a whole CLB. Candidates: a LUT3/FF cluster takes a free LUT3 as G, two free LUT3s
    // form a new cluster. Priority goes to the one supplying reset or clock of the FF (G drives both inside the
    // CLB), then to the number of shared inputs; pairs with nothing in common only while it is still too tight.
    // clb_cells_valid checks each pair like a placed CLB.
    void pair_lut3()
    {
        int n_lut3 = 0, n_whole = 0, n_clb = 0;
        std::vector<CellInfo *> roots, free; // LUT3/FF clusters with a free G, LUT3s without a cluster
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            n_whole += ci->type.in(id_XC2000_LUT4, id_XC2000_FGM);
            if (ci->type != id_XC2000_LUT3)
                continue;
            n_lut3++;
            if (ci->cluster == ClusterId())
                free.push_back(ci);
            else if (ci->cluster == ci->name)
                roots.push_back(ci);
        }
        for (BelId bel : ctx->getBels())
            n_clb += ctx->getBelType(bel) == id_DFF;
        if (n_lut3 + n_whole <= n_clb)
            return;
        auto by_name = [&](const CellInfo *a, const CellInfo *b) { return a->name.str(ctx) < b->name.str(ctx); };
        std::sort(roots.begin(), roots.end(), by_name);
        std::sort(free.begin(), free.end(), by_name);
        auto ff_of = [&](const CellInfo *root) -> const CellInfo * {
            for (const CellInfo *c : root->constr_children)
                if (c->type == id_XC2000_DFF)
                    return c;
            return nullptr;
        };
        auto score = [&](const CellInfo *a, const CellInfo *b, const CellInfo *ff) {
            int s = 0;
            const NetInfo *o = b->getPort(id_O);
            if (ff && o && (ff->getPort(id_R) == o || ff->getPort(id_CLK) == o))
                s += 10;
            for (int i = 0; ff && i < 3; i++) // G reads the Q of this FF: stays inside the CLB
                if (b->getPort(lut_in(i)) && b->getPort(lut_in(i)) == ff->getPort(id_Q))
                    s += 3;
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++) {
                    const NetInfo *n = a->getPort(lut_in(i));
                    if (n && n == b->getPort(lut_in(j)))
                        s++;
                }
            return s;
        };
        struct Cand
        {
            int score;
            CellInfo *f, *g;
        };
        std::vector<Cand> cands;
        for (CellInfo *r : roots)
            for (CellInfo *g : free)
                if (clb_cells_valid(r, g, nullptr, nullptr, ff_of(r), ""))
                    cands.push_back({score(r, g, ff_of(r)), r, g});
        for (size_t i = 0; i < free.size(); i++)
            for (size_t j = i + 1; j < free.size(); j++)
                if (clb_cells_valid(free[i], free[j], nullptr, nullptr, nullptr, ""))
                    cands.push_back({score(free[i], free[j], nullptr), free[i], free[j]});
        std::stable_sort(cands.begin(), cands.end(), [](const Cand &a, const Cand &b) { return a.score > b.score; });
        // CLBs needed: LUT4/FGM, LUT3 clusters and single LUT3s; target 85 % of the CLBs
        int demand = n_whole + int(roots.size() + free.size()), target = n_clb * 85 / 100, paired = 0, swapped = 0;
        pool<IdString> used;
        for (const Cand &c : cands) {
            if (c.score == 0 && demand <= target)
                break;
            if (used.count(c.f->name) || used.count(c.g->name))
                continue;
            used.insert(c.f->name);
            used.insert(c.g->name);
            c.f->cluster = c.f->name;
            c.f->constr_abs_z = false;
            c.f->constr_children.push_back(c.g);
            c.g->cluster = c.f->name;
            c.g->constr_x = c.g->constr_y = 0;
            c.g->constr_z = Z_G - Z_F;
            c.g->constr_abs_z = false;
            demand--;
            paired++;
            // If G reads the Q of this CLB's FF on input 1 or 2, pack() moves it to input 3 as for the D LUT:
            // otherwise Q would have to leave via X/Y and come back to A-D over the routing
            const CellInfo *ff = ff_of(c.f);
            const NetInfo *q = ff ? ff->getPort(id_Q) : nullptr;
            if (q && c.g->getPort(lut_in(2)) != q) {
                const Table t = tables(c.g).at(0);
                for (int i = 0; i < 2; i++) {
                    if (c.g->getPort(lut_in(i)) != q)
                        continue;
                    swap_lut_inputs(c.g, t, i, 2);
                    if (clb_cells_valid(c.f, c.g, nullptr, nullptr, ff, ""))
                        swapped++;
                    else
                        swap_lut_inputs(c.g, t, i, 2); // undo: this way the CLB would no longer be legal
                    break;
                }
            }
        }
        log_info("CLB pairs: %d LUT3 placed together as F and G (%d LUT cells for %d CLBs), about %d CLBs needed, "
                 "%d Q feedback inputs of G moved to input 3.\n",
                 paired, n_lut3 + n_whole, n_clb, demand, swapped);
    }

    // Timing of the storage element by kind (xc2064_arch_gen.py, set_timings): FF with rising/falling edge or latch
    // (transparent at clock 1 or 0), plus S/R -> Q and, for the latch, D -> Q as combinational arcs. nextpnr aborts
    // on a combinational loop; an arc is therefore left out if Q leads back to its input via logic (LUTs, FGM, such
    // arcs of other storage elements).
    void dff_timing()
    {
        if (!ctx->speed_grade)
            return;
        auto param = [](const CellInfo *ci, IdString p) {
            auto it = ci->params.find(p);
            return it != ci->params.end() && it->second.as_int64() != 0;
        };
        const IdString latch = ctx->id("LATCH"), clkinv = ctx->id("CLKINV");
        // Nets (names) that Q reaches via combinational paths
        auto reaches = [&](const CellInfo *start) {
            pool<IdString> seen;
            std::vector<const NetInfo *> todo{start->getPort(id_Q)};
            while (!todo.empty()) {
                const NetInfo *n = todo.back();
                todo.pop_back();
                if (!n || seen.count(n->name))
                    continue;
                seen.insert(n->name);
                for (auto &u : n->users) {
                    const CellInfo *c = u.cell;
                    if (c->type.in(id_XC2000_LUT3, id_XC2000_LUT4, id_XC2000_FGM))
                        todo.push_back(c->getPort(id_O));
                    else if (c->type == id_XC2000_DFF && (u.port.in(id_S, id_R) || (u.port == id_D && param(c, latch))))
                        todo.push_back(c->getPort(id_Q));
                }
            }
            return seen;
        };
        int ffs = 0, latches = 0, dropped = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type != id_XC2000_DFF)
                continue;
            bool is_latch = param(ci, latch), inv = param(ci, clkinv);
            bool has_sr = ci->getPort(id_S) || ci->getPort(id_R);
            auto seen = reaches(ci);
            auto loops = [&](IdString port) { // does Q reach this input?
                const NetInfo *n = ci->getPort(port);
                return n && seen.count(n->name);
            };
            bool d_arc = is_latch && !loops(id_D);
            bool sr_arc = has_sr && !loops(id_S) && !loops(id_R);
            dropped += (is_latch && !d_arc) + (has_sr && !sr_arc);
            IdString variant = ctx->idf("XC2000_DFF.%s%s%s%s", is_latch ? "L" : "FF", inv ? "N" : "P",
                                        d_arc ? ".D" : "", sr_arc ? ".SR" : "");
            int idx = ctx->get_cell_timing_idx(variant);
            if (idx != -1)
                ci->timing_index = idx;
            (is_latch ? latches : ffs)++;
        }
        if (ffs || latches)
            log_info("Timing of storage elements: %d flip-flops, %d latches, %d set/reset or transparency arcs left out "
                     "(combinational loop).\n",
                     ffs, latches, dropped);
    }

    bool clkbuf_enabled() const { return clkbuf; }

    // An unconnected LUT input still reads a line in the chip (the default setting of its mux): the LUT contents
    // must therefore not depend on it. For both values INIT takes the half with input = 0. For the FGM this applies
    // to each of the two tables; S is mandatory (B always selects in the chip).
    int fold_unused_lut_inputs()
    {
        int n = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type == id_XC2000_FGM && !ci->getPort(id_S))
                log_error("%s: XC2000_FGM without S (B selects between F and G)\n", ctx->nameOf(ci));
            for (const Table &t : tables(ci)) {
                uint64_t init = init_of(ci, t), next = init;
                for (int i = 0; i < t.width(); i++)
                    if (!ci->getPort(t.ports[i]))
                        next = fold_input(next, t.width(), i, 0), n++;
                if (next != init)
                    set_init(ci, t, next);
            }
        }
        return n;
    }

    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        if (ctx->getBelType(bel) == id_IOB)
            return iob_clock_valid(bel, explain_invalid);
        if (!ctx->getBelType(bel).in(id_LUT3, id_LUT4, id_FGM, id_DFF))
            return true;
        Loc l = ctx->getBelLocation(bel);
        return clb_valid(l.x, l.y, explain_invalid);
    }

    // Primitives (cell types with prefix XC2000_) -> Bel type they sit on
    static IdString bel_type_for(IdString cell_type)
    {
        switch (cell_type.index) {
        case id_XC2000_LUT3.index:
            return id_LUT3;
        case id_XC2000_LUT4.index:
            return id_LUT4;
        case id_XC2000_FGM.index:
            return id_FGM;
        case id_XC2000_DFF.index:
            return id_DFF;
        case id_XC2000_INBUF.index:
        case id_XC2000_INFF.index:
        case id_XC2000_OUTBUF.index:
        case id_XC2000_TOBUF.index:
        case id_XC2000_IOBUF.index:
            return id_IOB;
        }
        return cell_type;
    }

    IdString getBelBucketForCellType(IdString cell_type) const override { return bel_type_for(cell_type); }

    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        // an IOB only if its pad has a pin in the selected package
        IdString t = ctx->getBelType(bel);
        return t == bel_type_for(cell_type) && (t != id_IOB || bonded.count(bel));
    }

  private:
    HimbaechelHelpers h;
    dict<IdString, BelId> pad_bels;  // package pin -> IOB Bel
    pool<BelId> bonded;              // IOB Bels with a pin in the package
    std::array<std::vector<BelId>, 4> side_iobs; // IOB Bels per side (top, right, bottom, left)
    static int side_index(char side) { return side == 'T' ? 0 : side == 'R' ? 1 : side == 'B' ? 2 : 3; }

    // Latched inputs (XC2000_INFF): all IOBs of one side are connected to the same clock line, so their K must be
    // the same net
    bool iob_clock_valid(BelId bel, bool explain) const
    {
        const CellInfo *ci = ctx->getBoundBelCell(bel);
        if (!ci || ci->type != id_XC2000_INFF)
            return true;
        const NetInfo *k = ci->getPort(id_K);
        char side = io_side(ctx->getBelLocation(bel));
        for (BelId other : side_iobs[side_index(side)]) {
            const CellInfo *oc = ctx->getBoundBelCell(other);
            if (other == bel || !oc || oc->type != id_XC2000_INFF || oc->getPort(id_K) == k)
                continue;
            if (explain)
                log_info("%s and %s: latched inputs of one side (%c) with different clocks %s and %s\n",
                         ctx->nameOf(ci->getPort(id_PAD)), ctx->nameOf(oc->getPort(id_PAD)), side, ctx->nameOf(k),
                         ctx->nameOf(oc->getPort(id_K)));
            return false;
        }
        return true;
    }

    // After fixing the pins: latched inputs with different clocks on one side are an error
    void check_iob_clocks()
    {
        int n = 0;
        for (auto &cell : ctx->cells) {
            const CellInfo *ci = cell.second.get();
            if (ci->type != id_XC2000_INFF)
                continue;
            n++;
            if (ci->bel != BelId() && !iob_clock_valid(ci->bel, true))
                log_error("Input '%s' at %s: all latched inputs of one side must share the same clock (change the "
                          "PCF or keep the FFs in the CLBs: synth_xc2064 -noiobff)\n",
                          ctx->nameOf(ci->getPort(id_PAD)), ctx->getBelName(ci->bel)[1].c_str(ctx));
        }
        if (n)
            log_info("%d registered inputs in IOBs (XC2000_INFF).\n", n);
    }
    std::string package = "PC68";
    std::array<std::array<BelId, 2>, 2> clock_pads; // per buffer (GCLK, ACLK) its pads, CLOCK_PADS
    bool clkbuf = true;                             // use the clock buffers (--vopt noclkbuf: no)
    pool<IdString> clock_only_nets;                 // clocks at clock pads that only clock FFs (preRoute)
    pool<PipId> pad_exit_pips;                      // ... and the pips from there into the general routing

    IdString lut_in(int i) const { return ctx->idf("I[%d]", i); }
    IdString fgm_in(int half, int i) const { return ctx->idf("%c[%d]", "FG"[half], i); } // half 0: F, 1: G

    // --- Function tables -----------------------------------------------------------------------
    // LUT3 and LUT4 have one table (INIT with the inputs I[...]), FGM two (INIT_F with F[...], INIT_G with G[...]);
    // bit a of the table is the output for the inputs a (input i = bit i)
    struct Table
    {
        IdString param;
        std::vector<IdString> ports;
        int width() const { return int(ports.size()); }
    };
    std::vector<Table> tables(const CellInfo *ci) const
    {
        std::vector<Table> r;
        if (ci->type.in(id_XC2000_LUT3, id_XC2000_LUT4)) {
            r.push_back({id_INIT, {}});
            for (int i = 0; i < (ci->type == id_XC2000_LUT4 ? 4 : 3); i++)
                r.back().ports.push_back(lut_in(i));
        } else if (ci->type == id_XC2000_FGM) {
            for (int h = 0; h < 2; h++) {
                r.push_back({h ? id_INIT_G : id_INIT_F, {}});
                for (int i = 0; i < 3; i++)
                    r.back().ports.push_back(fgm_in(h, i));
            }
        }
        return r;
    }
    static uint64_t init_of(const CellInfo *ci, const Table &t) { return uint64_t(ci->params.at(t.param).as_int64()); }
    static void set_init(CellInfo *ci, const Table &t, uint64_t v)
    {
        ci->params[t.param] = Property(int64_t(v), 1 << t.width());
    }
    // Table with input idx fixed to value: the same contents for both values of the input
    static uint64_t fold_input(uint64_t init, int width, int idx, int value)
    {
        uint64_t r = 0;
        for (int a = 0; a < (1 << width); a++)
            if ((init >> ((a & ~(1 << idx)) | (value << idx))) & 1)
                r |= uint64_t(1) << a;
        return r;
    }

    // --- Packing: Q feedback -----------------------------------------------------------------
    // Only input 3 (I[2], for the FGM F[2] or G[2]) of a function generator can use Q directly. If the table that
    // feeds an FF has the Q of that FF on another input, the inputs are swapped (contents permuted).
    int route_q_feedback_to_i2()
    {
        int moved = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ff = cell.second.get();
            if (ff->type != id_XC2000_DFF)
                continue;
            NetInfo *d = ff->getPort(id_D), *q = ff->getPort(id_Q);
            if (!d || !q || !d->driver.cell)
                continue;
            CellInfo *lut = d->driver.cell;
            for (const Table &t : tables(lut)) {
                if (lut->getPort(t.ports.at(2)) == q)
                    continue;
                for (int i = 0; i < t.width(); i++) {
                    if (i == 2 || lut->getPort(t.ports[i]) != q)
                        continue;
                    swap_lut_inputs(lut, t, i, 2);
                    moved++;
                    break;
                }
            }
        }
        return moved;
    }

    void swap_lut_inputs(CellInfo *lut, const Table &t, int a, int b)
    {
        IdString pa = t.ports.at(a), pb = t.ports.at(b);
        for (IdString p : {pa, pb})
            if (!lut->ports.count(p))
                lut->addInput(p);
        NetInfo *na = lut->getPort(pa), *nb = lut->getPort(pb);
        lut->disconnectPort(pa);
        lut->disconnectPort(pb);
        if (nb)
            lut->connectPort(pa, nb);
        if (na)
            lut->connectPort(pb, na);
        // Contents: bit i of the new = bit (i with address bits a, b swapped) of the old
        uint64_t old_init = init_of(lut, t), new_init = 0;
        for (int i = 0; i < (1 << t.width()); i++) {
            int j = i & ~((1 << a) | (1 << b));
            j |= (((i >> a) & 1) << b) | (((i >> b) & 1) << a);
            if ((old_init >> j) & 1)
                new_init |= uint64_t(1) << i;
        }
        set_init(lut, t, new_init);
    }

    // --- Legality -----------------------------------------------------------------------------
    const CellInfo *cell_at(int x, int y, int z) const
    {
        BelId bel = ctx->getBelByLocation(Loc(x, y, z));
        return bel == BelId() ? nullptr : ctx->getBoundBelCell(bel);
    }

    // Net comes directly from the input driver of a pad (XC2000_INBUF or O of an XC2000_IOBUF)
    static bool is_pad_input(const NetInfo *net)
    {
        const CellInfo *drv = net->driver.cell;
        return drv && drv->type.in(id_XC2000_INBUF, id_XC2000_IOBUF) && net->driver.port == id_O;
    }

    // Clock buffer the net reaches from its pad: 0 GCLK (P9, P11), 1 ACLK (P43, P46), -1 none
    int clock_buffer(const NetInfo *net) const
    {
        const CellInfo *drv = net->driver.cell;
        if (!clkbuf_enabled() || !is_pad_input(net))
            return -1;
        BelId bel = drv->bel;
        auto fixed = drv->attrs.find(id_BEL);
        if (bel == BelId() && fixed != drv->attrs.end())
            bel = ctx->getBelByNameStr(fixed->second.as_string());
        for (int b = 0; bel != BelId() && b < 2; b++)
            for (BelId pad : clock_pads[b])
                if (bel == pad)
                    return b;
        return -1;
    }

    struct Req
    {
        const NetInfo *net;
        uint8_t opts;
    };

    // Assign an allowed source to each request; A-D carry at most one net each
    static bool assign(std::vector<Req> &reqs, size_t i, std::array<const NetInfo *, 4> &inputs)
    {
        if (i == reqs.size())
            return true;
        const Req &r = reqs.at(i);
        // An internal source (Q, F, G, K; already checked as matching) occupies none of the inputs A-D
        if (r.opts & ~(M(S_A) | M(S_B) | M(S_C) | M(S_D)))
            return assign(reqs, i + 1, inputs);
        for (int s = S_A; s <= S_D; s++) {
            if (!(r.opts & (1u << s)))
                continue;
            if (inputs[s] && inputs[s] != r.net)
                continue;
            const NetInfo *prev = inputs[s];
            inputs[s] = r.net;
            if (assign(reqs, i + 1, inputs))
                return true;
            inputs[s] = prev;
        }
        return false;
    }

    bool clb_valid(int x, int y, bool explain) const
    {
        return clb_cells_valid(cell_at(x, y, Z_F), cell_at(x, y, Z_G), cell_at(x, y, Z_FG), cell_at(x, y, Z_FGM),
                               cell_at(x, y, Z_FF), explain ? stringf("X%dY%d", x, y) : std::string());
    }

    // Is this occupancy of a CLB (F, G, FG, FGM, FF; nullptr = free) legal? Also for cells not placed yet (pairs in
    // pack()). where: location for the explanation in the log, empty = no explanation
    bool clb_cells_valid(const CellInfo *f, const CellInfo *g, const CellInfo *fg, const CellInfo *fgm,
                         const CellInfo *ff, const std::string &where) const
    {
        const bool explain = !where.empty();
        const char *at = where.c_str();

        // 1. The combined F/G (FG: function of 4 variables, FGM: mux mode) occupies both function generators, its
        // output is on both F and G
        const CellInfo *both = fg ? fg : fgm;
        if (both && (f || g || (fg && fgm))) {
            if (explain)
                log_info("%s: %s occupied together with another function generator\n", at, fg ? "LUT4 (FG)" : "FGM");
            return false;
        }
        const NetInfo *f_out = f ? f->getPort(id_O) : both ? both->getPort(id_O) : nullptr;
        const NetInfo *g_out = g ? g->getPort(id_O) : both ? both->getPort(id_O) : nullptr;
        const NetInfo *q_out = ff ? ff->getPort(id_Q) : nullptr;

        // 2. The FF gets its data only from F or FG/FGM of this CLB
        if (ff) {
            const NetInfo *d = ff->getPort(id_D);
            if (d && (!f_out || d != f_out)) {
                if (explain)
                    log_info("%s: FF data does not come from F or FG/FGM of this CLB\n", at);
                return false;
            }
        }

        // 3. All inputs reachable via the multiplexers of the original, A-D one net each
        std::vector<Req> reqs;
        auto add = [&](const NetInfo *net, uint8_t opts) {
            if (!net)
                return;
            if (net != q_out)
                opts &= ~M(S_Q);
            if (!f_out || net != f_out)
                opts &= ~M(S_F);
            if (!g_out || net != g_out)
                opts &= ~M(S_G);
            // K comes from GCLK or from the vertical long.2 of the column, which any net can reach (this is how
            // XACT clocks in COUNTER.BIT); the router has to resolve two clocks in one column via C
            reqs.push_back({net, opts});
        };
        for (const CellInfo *c : {f, g})
            if (c)
                for (int i = 0; i < 3; i++)
                    add(c->getPort(lut_in(i)), LUT_IN_OPTS[i]);
        if (fg)
            for (int i = 0; i < 4; i++)
                add(fg->getPort(lut_in(i)), LUT_IN_OPTS[i]);
        if (fgm) {
            for (int h = 0; h < 2; h++)
                for (int i = 0; i < 3; i++)
                    add(fgm->getPort(fgm_in(h, i)), LUT_IN_OPTS[i]);
            add(fgm->getPort(id_S), LUT_IN_OPTS[3]);
        }
        if (ff) {
            add(ff->getPort(id_CLK), FF_CLK_OPTS);
            add(ff->getPort(id_S), FF_SET_OPTS);
            add(ff->getPort(id_R), FF_RES_OPTS);
        }
        for (const Req &r : reqs)
            if (!r.opts) {
                if (explain)
                    log_info("%s: net %s cannot reach its pin via any multiplexer\n", at, r.net->name.c_str(ctx));
                return false;
            }
        std::sort(reqs.begin(), reqs.end(),
                  [](const Req &a, const Req &b) { return __builtin_popcount(a.opts) < __builtin_popcount(b.opts); });
        std::array<const NetInfo *, 4> inputs{};
        if (!assign(reqs, 0, inputs)) {
            if (explain)
                log_info("%s: input signals do not fit onto the multiplexers of A-D\n", at);
            return false;
        }

        // 4. Only X and Y lead out of the CLB: at most two signals may leave it. Only the fixed paths F -> D and set,
        // G -> reset and clock (FG/FGM on both) and Q -> input 3 stay inside the CLB.
        auto internal = [&](const NetInfo *n, const PortRef &u) {
            if (u.cell == ff) {
                if (u.port.in(id_D, id_S))
                    return n == f_out;
                if (u.port.in(id_R, id_CLK))
                    return n == g_out;
                return false;
            }
            if (n != q_out)
                return false;
            if (u.cell == f || u.cell == g || u.cell == fg)
                return u.port == lut_in(2);
            if (u.cell == fgm)
                return u.port == fgm_in(0, 2) || u.port == fgm_in(1, 2);
            return false;
        };
        int leaving = 0;
        const NetInfo *seen[3] = {nullptr, nullptr, nullptr};
        int ns = 0;
        for (const NetInfo *n : {f_out, g_out, q_out}) {
            if (!n || std::find(seen, seen + ns, n) != seen + ns)
                continue;
            seen[ns++] = n;
            bool out = false;
            for (auto &u : n->users)
                if (!internal(n, u)) {
                    out = true;
                    break;
                }
            leaving += out;
        }
        if (leaving > 2) {
            if (explain)
                log_info("%s: three signals would have to leave the CLB, but there are only two (X and Y)\n", at);
            return false;
        }
        return true;
    }

    // router2 searches each net only within its bounding box plus a margin (default 3 tiles). With 4 tracks per
    // channel that is not always enough: two nets then keep taking turns on one wire and router2 never finishes.
    // On the 10x10 grid every net may therefore use the whole chip (a custom value via the settings
    // router2/bbMargin/x and /y remains possible).
    void preRoute() override
    {
        int margin = std::max(ctx->getGridDimX(), ctx->getGridDimY());
        for (const char *k : {"router2/bbMargin/x", "router2/bbMargin/y"})
            if (!ctx->settings.count(ctx->id(k)))
                ctx->settings[ctx->id(k)] = std::to_string(margin);
        // A clock at a pad of a clock buffer (P9/P11: GCLK, P43/P46: ACLK) that only clocks storage elements runs
        // entirely over the buffer, as with XACT (low skew). Otherwise the router would take the shorter path from
        // the pad over the general routing to nearby CLBs. If both pads of a buffer carry such clocks, the one with
        // the most storage elements gets the buffer.
        clock_only_nets.clear();
        pad_exit_pips.clear();
        for (int b = 0; clkbuf_enabled() && b < 2; b++) {
            BelId pad;
            const NetInfo *net = nullptr;
            for (BelId p : clock_pads[b]) {
                const CellInfo *ci = p == BelId() ? nullptr : ctx->getBoundBelCell(p);
                const NetInfo *n = ci ? ci->getPort(id_O) : nullptr;
                if (!n || n->users.entries() == 0)
                    continue;
                bool only_ff = true;
                for (auto &u : n->users)
                    only_ff &= u.cell->type == id_XC2000_DFF && u.port == id_CLK;
                if (!only_ff)
                    continue;
                if (net) {
                    bool more = n->users.entries() > net->users.entries();
                    log_info("Clocks '%s' and '%s' share %s, '%s' runs over the general routing.\n", ctx->nameOf(net),
                             ctx->nameOf(n), CLOCK_BUFFERS[b], ctx->nameOf(more ? net : n));
                    if (!more)
                        continue;
                }
                pad = p;
                net = n;
            }
            if (!net)
                continue;
            clock_only_nets.insert(net->name);
            Loc pl = ctx->getBelLocation(pad);
            for (PipId pip : ctx->getPipsDownhill(ctx->getBelPinWire(pad, id_O))) {
                int32_t id = local_gfx_id(ctx->getPipDstWire(pip), pl, -1);
                if (id != GFX_WIRE_GCLK && id != GFX_WIRE_ACLK)
                    pad_exit_pips.insert(pip);
            }
        }
    }

    bool checkPipAvailForNet(PipId pip, const NetInfo *net) const override
    {
        if (!checkPipAvail(pip))
            return false;
        return !(net && pad_exit_pips.count(pip) && clock_only_nets.count(net->name));
    }

    // --vopt noclkbuf blocks the inputs of the clock buffers (codes determined with MAKEBITS): clocks then run like
    // any signal over the general routing, to K via the vertical long.2 of the column
    bool checkPipAvail(PipId pip) const override
    {
        if (clkbuf)
            return true;
        const Xc2064PipExtraPOD *x = pip_extra(pip);
        return !(x && x->kind == PIP_CLKBUF);
    }

    const Xc2064PipExtraPOD *pip_extra(PipId pip) const
    {
        const auto &p = chip_pip_info(ctx->chip_info, pip);
        return p.extra_data.is_null() ? nullptr : reinterpret_cast<const Xc2064PipExtraPOD *>(p.extra_data.get());
    }

    // --- Configuration as text (--vopt out=, for xc2064pack) ---------------------------------------
    // Format: arch/xc2064/xc2064db/config.py. The routing pips carry their text line from the graph in their extra
    // data; CLBs and IOBs follow from the cells and the pips inside the CLB. xc2064pack derives the direction of
    // the repowering buffers ("bidi auto"), everything else stays in the XACT default state.
    void postRoute() override
    {
        if (ctx->args.options.count("out"))
            write_config(ctx->args.options.at("out").as<std::string>());
    }

    std::string tile_wire_name(int tile, int index) const
    {
        return IdString(chip_tile_info(ctx->chip_info, tile).wires[index].name).str(ctx);
    }
    // Name (in the tile of the pip) of the source driving wire w in its net; "" if none
    std::string driver_name(WireId w) const
    {
        if (w == WireId())
            return "";
        const NetInfo *net = ctx->getBoundWireNet(w);
        if (!net)
            return "";
        auto it = net->wires.find(w);
        if (it == net->wires.end() || it->second.pip == PipId())
            return "";
        PipId pip = it->second.pip;
        return tile_wire_name(pip.tile, chip_pip_info(ctx->chip_info, pip).src_wire);
    }
    std::string pin_driver(int x, int y, int z, IdString pin) const
    {
        BelId bel = ctx->getBelByLocation(Loc(x, y, z));
        return driver_name(ctx->getBelPinWire(bel, pin));
    }

    // "clb" line of a CLB (fields: xc2064db/blocks.py), "" if the CLB is unused
    std::string clb_config(int x, int y) const
    {
        const CellInfo *f = cell_at(x, y, Z_F), *g = cell_at(x, y, Z_G), *fg = cell_at(x, y, Z_FG);
        const CellInfo *fgm = cell_at(x, y, Z_FGM), *ff = cell_at(x, y, Z_FF);
        Loc loc(x, y, 0);
        std::string xs = driver_name(tile_wire(loc, GFX_WIRE_X)), ys = driver_name(tile_wire(loc, GFX_WIRE_Y));
        if (!f && !g && !fg && !fgm && !ff && xs.empty() && ys.empty())
            return "";
        // FG/FGM is on both F and G (F/M or G in the original)
        auto out_name = [](const std::string &s) { return s == "G_O" ? "G" : s == "Q" || s.empty() ? "Q" : "F"; };
        auto inputs = [&](int z, int half) { // half -1: I[0..2] of a LUT, 0/1: F[...]/G[...] of the FGM
            static const char *def[3] = {"B", "C", "Q"};
            std::string r;
            for (int i = 0; i < 3; i++) {
                std::string s = pin_driver(x, y, z, half < 0 ? lut_in(i) : fgm_in(half, i));
                r += (i ? ":" : "") + (s.empty() ? std::string(def[i]) : s);
            }
            return r;
        };
        auto init = [](const CellInfo *c, IdString p) {
            return c ? unsigned(c->params.at(p).as_int64()) : 0u;
        };
        std::string base = "FG", fin, gin;
        unsigned lutf, lutg;
        if (fg) { // B = 1: table F = INIT[15:8]
            base = "F", fin = gin = inputs(Z_FG, -1);
            lutf = (init(fg, id_INIT) >> 8) & 0xFF, lutg = init(fg, id_INIT) & 0xFF;
        } else if (fgm) {
            base = "FGM", fin = inputs(Z_FGM, 0), gin = inputs(Z_FGM, 1);
            lutf = init(fgm, id_INIT_F) & 0xFF, lutg = init(fgm, id_INIT_G) & 0xFF;
        } else {
            fin = inputs(Z_F, -1), gin = inputs(Z_G, -1);
            lutf = init(f, id_INIT) & 0xFF, lutg = init(g, id_INIT) & 0xFF;
        }
        std::string q = "LATCH", clk, set, res;
        if (ff) {
            auto param = [&](const char *p) {
                auto it = ff->params.find(ctx->id(p));
                return it != ff->params.end() && it->second.as_int64() != 0;
            };
            q = param("LATCH") ? "LATCH" : "FF";
            std::string c = pin_driver(x, y, Z_FF, id_CLK);
            if (!c.empty())
                clk = std::string(c == "K" ? "K" : c == "C" ? "C" : "G") + (param("CLKINV") ? ":NOT" : "");
            std::string s = pin_driver(x, y, Z_FF, id_S), r = pin_driver(x, y, Z_FF, id_R);
            set = s.empty() ? "" : s == "A" ? "A" : "F";
            res = r.empty() ? "" : r == "D" ? "D" : "G";
        }
        return stringf("BASE:%s F:%s G:%s LUTF:%02X LUTG:%02X X:%s Y:%s Q:%s SET:%s RES:%s CLK:%s", base.c_str(),
                       fin.c_str(), gin.c_str(), lutf, lutg, out_name(xs), out_name(ys), q.c_str(), set.c_str(),
                       res.c_str(), clk.c_str());
    }

    void write_config(const std::string &file)
    {
        std::ofstream out(file);
        if (!out)
            log_error("Cannot write '%s'\n", file.c_str());
        out << "# XC2064 configuration from nextpnr-himbaechel (arch/xc2064, format: xc2064db/config.py)\n";
        out << "device XC2064\npackage " << package << "\nbidi auto\n";
        std::vector<std::string> lines;
        for (BelId bel : ctx->getBels()) { // IOBs: port, direct input, mode of the output driver
            const CellInfo *ci = ctx->getBoundBelCell(bel);
            if (!ci || ctx->getBelType(bel) != id_IOB)
                continue;
            std::string pin = ctx->getBelName(bel)[1].str(ctx);
            const NetInfo *pad = ci->getPort(id_PAD);
            bool input = ci->type.in(id_XC2000_INBUF, id_XC2000_INFF);
            const char *dir = input ? "input" : ci->type == id_XC2000_IOBUF ? "inout" : "output";
            if (pad)
                lines.push_back(stringf("port %s %s %s", pin.c_str(), pad->name.c_str(ctx), dir));
            // latched input: the FF in the IOB, clock via the K mux of the side (a routing pip); name of the
            // register for the way back (xc2064netlist)
            lines.push_back("iob " + pin + (ci->type == id_XC2000_INFF ? " I:Q" : " I:PAD"));
            const NetInfo *q = ci->type == id_XC2000_INFF ? ci->getPort(id_O) : nullptr;
            if (q)
                lines.push_back(stringf("reg %s %s", pin.c_str(), q->name.c_str(ctx)));
            if (input)
                lines.push_back("mux " + pin + ".T off");
            else if (ci->type == id_XC2000_OUTBUF)
                lines.push_back("mux " + pin + ".T on");
        }
        for (int y = 1; y <= 8; y++)
            for (int x = 1; x <= 8; x++) {
                std::string c = clb_config(x, y);
                if (!c.empty())
                    lines.push_back(stringf("clb %c%c %s", 'A' + y - 1, 'A' + x - 1, c.c_str()));
                const CellInfo *ff = cell_at(x, y, Z_FF);
                const NetInfo *q = ff ? ff->getPort(id_Q) : nullptr;
                if (q) // name of the register for the way back (xc2064netlist)
                    lines.push_back(stringf("reg %c%c %s", 'A' + y - 1, 'A' + x - 1, q->name.c_str(ctx)));
            }
        std::set<std::string> routing; // routing pips (both directions of a switch: one line)
        for (auto &n : ctx->nets)
            for (auto &w : n.second->wires) {
                PipId pip = w.second.pip;
                const Xc2064PipExtraPOD *x = pip == PipId() ? nullptr : pip_extra(pip);
                if (x)
                    routing.insert(IdString(x->cfg).str(ctx));
            }
        for (auto &l : lines)
            out << l << "\n";
        for (auto &l : routing)
            out << l << "\n";
        log_info("Wrote configuration for xc2064pack to %s (%d lines).\n", file.c_str(),
                 int(lines.size() + routing.size()));
    }

    // --- GUI: schematic -----------------------------------------------------------------------
    // Tile coordinates 0..1 with y pointing down (like the datasheet and die photos, X0Y0 top left). The nextpnr
    // GUI draws with y pointing up, which is why box()/line() mirror at the horizontal.
    //
    // Routing (xc2064db.graph): top left the switch matrices 8.1/8.2, to their right the channel above the CLB,
    // below them the channel left of the CLB, with the lines in the order and spacing of Shirriff's draw.js:
    // vertical local.1-4, the fifth line (local.5, in the channel on the track of local.6), long.1/long.2, GCLK;
    // horizontal local.0 (junction of the fifth), local.1/3/4/5 and long.1. Other lines at the edge (see
    // VPOS/HPOS). ACLK runs horizontally at the bottom.
    // CLB (frame 0.37..0.95) following the block diagram in the datasheet, from left to right:
    //   inputs A B C D as rows from the left (A from the channel above, D from the channel below), feedback Q
    //   combinational logic: multiplexers of the LUT inputs, LUT F, LUT G, FG as a frame around both with the
    //   F/G multiplexer (B selects), FGM (mux mode) as the same multiplexer without a frame
    //   distributors F, FG, G with the multiplexers for set (top), data, clock and reset (bottom)
    //   storage element: D and clock on the left, S top, R bottom, Q right
    //   output rails with the multiplexers X and Y, both leaving to the right through the channel on the right
    // A runs over the logic to the set multiplexer, C, K and D below it to clock and reset, Q around the bottom
    // back to the LUTs. Direct connections: X along the right edge up to C/D of the CLB above and down to A/B of
    // the CLB below, Y further right to B of the neighbouring CLB.
    // No line runs through a component. In the routing, each wire draws its whole line up to the crossings where
    // it can be switched, the pip only the box there (like metal and switches in the chip). In the CLB, pips are
    // taps with a dot (rail -> multiplexer input). Unused pips are dimmed, a used pip additionally shows its path
    // through the multiplexer.
    static constexpr int LAST = 9; // 9th switch matrix column/row

    float flip_y(float y) const { return ctx->getGridDimY() - y; }
    void box(std::vector<GraphicElement> &g, GraphicElement::style_t style, float x1, float y1, float x2,
             float y2) const
    {
        GraphicElement el;
        el.type = GraphicElement::TYPE_BOX;
        el.style = style;
        el.x1 = x1;
        el.y1 = flip_y(y2);
        el.x2 = x2;
        el.y2 = flip_y(y1);
        g.push_back(el);
    }
    void line(std::vector<GraphicElement> &g, GraphicElement::style_t style, float x1, float y1, float x2,
              float y2) const
    {
        GraphicElement el;
        el.type = GraphicElement::TYPE_LINE;
        el.style = style;
        el.x1 = x1;
        el.y1 = flip_y(y1);
        el.x2 = x2;
        el.y2 = flip_y(y2);
        g.push_back(el);
    }
    // Polyline in tile coordinates
    void poly(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc,
              std::initializer_list<std::pair<float, float>> pts) const
    {
        const std::pair<float, float> *prev = nullptr;
        for (auto &p : pts) {
            if (prev)
                line(g, style, loc.x + prev->first, loc.y + prev->second, loc.x + p.first, loc.y + p.second);
            prev = &p;
        }
    }
    // Pip as a box at the crossing point
    void pip_box(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float x, float y) const
    {
        box(g, style, loc.x + x - 0.006, loc.y + y - 0.006, loc.x + x + 0.006, loc.y + y + 0.006);
    }

    // --- Position of the channel lines ---
    // Following Shirriff's draw.js (order and spacing of the screen coordinates), separately for column A (left
    // edge), B-H and I (right edge) or row A (top), B-H and I (bottom). Vertical lines lie in the channel left of
    // the CLB (x 0..0.36), horizontal ones in the channel above it (y 0..0.36); -1: does not exist there.
    enum VLine
    {
        V_LOC1, V_LOC2, V_LOC3, V_LOC4, V_LOC5, V_LOC6, V_LONG1, V_LONG2, V_LONG3, V_LONG4, V_CLK, V_X, V_N
    };
    enum HLine
    {
        H_LOC0, H_LOC1, H_LOC2, H_LOC3, H_LOC4, H_LOC5, H_LONG1, H_LONG2, H_LONG3, H_CLK, H_N
    };
    static constexpr float VPOS[3][V_N] = {
            // column A: long.2 22, local.1-4 26-38, long.3 44, long.4 48, clk 52, x 74
            {0.054, 0.078, 0.102, 0.126, -1, -1, -1, 0.030, 0.162, 0.186, 0.210, 0.342},
            // B-H: local.1-4 108-120, local.5 126, local.6 130, long.1 134, long.2 138, clk 142, x 146
            {0.040, 0.071, 0.102, 0.134, 0.181, 0.212, 0.243, 0.274, -1, -1, 0.305, 0.336},
            // column I: long.1 626, long.2 630, local.1-4 636-648, long.3 652
            {0.118, 0.149, 0.181, 0.212, -1, -1, 0.040, 0.071, 0.243, -1, -1, -1},
    };
    static constexpr float HPOS[3][H_N] = {
            // row A: CLK.AA.O 22, long.2 26, local.1-4 30-42, long.3 48
            {-1, 0.114, 0.156, 0.198, 0.240, -1, -1, 0.072, 0.303, 0.030},
            // B-H: local.0 112, local.1 114, local.3 118, local.4 122, local.5 126, long.1 132
            {0.030, 0.055, -1, 0.105, 0.155, 0.205, 0.280, -1, -1, -1},
            // row I: long.1 624, local.1-4 630-642, long.2 646, clk 652
            {-1, 0.103, 0.145, 0.187, 0.229, -1, 0.040, 0.271, -1, 0.334},
    };
    static int col_kind(int x) { return x <= 1 ? 0 : x >= LAST ? 2 : 1; }
    static int row_kind(int y) { return y <= 1 ? 0 : y >= LAST ? 2 : 1; }
    static float vx(int x, int l) { return VPOS[col_kind(x)][l]; }
    static float hy(int y, int l) { return HPOS[row_kind(y)][l]; }
    // right end of ACLK in II: the input of the buffer is there
    static float aclk_end() { return vx(LAST, V_LONG3) + 0.02f; }

    // Switch matrices 8.1 (m = 0) and 8.2 (m = 1): vertically local.1/2 or local.3/4, horizontally depending on the
    // row (G position of the pins, xc2064db.switches); none at the four corners of the chip
    static bool tile_has_sm(int x, int y)
    {
        return x >= 1 && x <= LAST && y >= 1 && y <= LAST && !((x == 1 || x == LAST) && (y == 1 || y == LAST));
    }
    static void sm_rows(int y, int m, int &h0, int &h1)
    {
        static constexpr int ROWS[3][2][2] = {{{H_LOC1, H_LOC2}, {H_LOC3, H_LOC4}},
                                              {{H_LOC1, H_LOC3}, {H_LOC4, H_LOC5}},
                                              {{H_LOC3, H_LOC4}, {H_LOC1, H_LOC2}}};
        h0 = ROWS[row_kind(y)][m][0], h1 = ROWS[row_kind(y)][m][1];
    }
    struct Box
    {
        float x0, y0, x1, y1;
    };
    static Box sm_box(int x, int y, int m)
    {
        const float e = 0.016;
        int h0, h1;
        sm_rows(y, m, h0, h1);
        return {vx(x, m ? V_LOC3 : V_LOC1) - e, hy(y, h0) - e, vx(x, m ? V_LOC4 : V_LOC2) + e, hy(y, h1) + e};
    }
    static int sm_of_v(int l) { return l >= V_LOC3 ? 1 : 0; }
    static int sm_of_h(int y, int h)
    {
        int h0, h1;
        sm_rows(y, 0, h0, h1);
        return h == h0 || h == h1 ? 0 : 1;
    }

    // Channel wire from the graphics ID: vertical or horizontal, line, neighbouring piece (dx, dy)
    struct Chan
    {
        bool ok, vert;
        int line, dx, dy;
    };
    static Chan chan(int32_t id)
    {
        auto in = [id](int32_t a, int32_t b) { return id >= a && id <= b; };
        if (in(GFX_WIRE_V1, GFX_WIRE_V5))
            return {true, true, V_LOC1 + (id - GFX_WIRE_V1), 0, 0};
        if (in(GFX_WIRE_V1_U, GFX_WIRE_V5_U))
            return {true, true, V_LOC1 + (id - GFX_WIRE_V1_U), 0, -1};
        if (in(GFX_WIRE_V1_R, GFX_WIRE_V5_R))
            return {true, true, V_LOC1 + (id - GFX_WIRE_V1_R), 1, 0};
        if (in(GFX_WIRE_V1_D, GFX_WIRE_V5_D))
            return {true, true, V_LOC1 + (id - GFX_WIRE_V1_D), 0, 1};
        if (in(GFX_WIRE_V1_RU, GFX_WIRE_V5_RU))
            return {true, true, V_LOC1 + (id - GFX_WIRE_V1_RU), 1, -1};
        if (in(GFX_WIRE_VL1, GFX_WIRE_VL4))
            return {true, true, V_LONG1 + (id - GFX_WIRE_VL1), 0, 0};
        if (in(GFX_WIRE_VL1_R, GFX_WIRE_VL4_R))
            return {true, true, V_LONG1 + (id - GFX_WIRE_VL1_R), 1, 0};
        if (id == GFX_WIRE_GCLK)
            return {true, true, V_CLK, 0, 0};
        if (in(GFX_WIRE_H1, GFX_WIRE_H5))
            return {true, false, H_LOC1 + (id - GFX_WIRE_H1), 0, 0};
        if (in(GFX_WIRE_H1_L, GFX_WIRE_H5_L))
            return {true, false, H_LOC1 + (id - GFX_WIRE_H1_L), -1, 0};
        if (in(GFX_WIRE_H1_D, GFX_WIRE_H5_D))
            return {true, false, H_LOC1 + (id - GFX_WIRE_H1_D), 0, 1};
        if (in(GFX_WIRE_H1_R, GFX_WIRE_H5_R))
            return {true, false, H_LOC1 + (id - GFX_WIRE_H1_R), 1, 0};
        if (in(GFX_WIRE_H1_LD, GFX_WIRE_H5_LD))
            return {true, false, H_LOC1 + (id - GFX_WIRE_H1_LD), -1, 1};
        if (in(GFX_WIRE_HL1, GFX_WIRE_HL3))
            return {true, false, H_LONG1 + (id - GFX_WIRE_HL1), 0, 0};
        if (in(GFX_WIRE_HL1_D, GFX_WIRE_HL3_D))
            return {true, false, H_LONG1 + (id - GFX_WIRE_HL1_D), 0, 1};
        if (id == GFX_WIRE_ACLK)
            return {true, false, H_CLK, 0, 0};
        return {false, false, 0, 0, 0};
    }
    // Position at a crossing: x of the vertical line (hline: the crossed horizontal one, -1 in the CLB), y of the
    // horizontal line. The own piece of the fifth line crosses local.3/4 on the track of local.6.
    static float chan_x(Loc loc, const Chan &c, int hline)
    {
        if (c.line == V_LOC5 && c.dx == 0 && c.dy == 0 && loc.y > 1 && (hline == H_LOC3 || hline == H_LOC4))
            return vx(loc.x, V_LOC6);
        return c.dx + vx(loc.x + c.dx, c.line);
    }
    static float chan_y(Loc loc, const Chan &c) { return c.dy + hy(loc.y + c.dy, c.line); }
    // Line that ends at a switch matrix in this tile (local.1-4 vertical, the rows of the matrices)
    static bool sm_line(Loc loc, const Chan &c)
    {
        if (!tile_has_sm(loc.x, loc.y))
            return false;
        if (c.vert)
            return c.line <= V_LOC4 && c.dx == 0;
        int a, b, d, e;
        sm_rows(loc.y, 0, a, b);
        sm_rows(loc.y, 1, d, e);
        return c.dy == 0 && (c.line == a || c.line == b || c.line == d || c.line == e);
    }
    // Pin of a switch matrix: piece above/below or left/right at the edge of the matrix
    static std::pair<float, float> sm_pin_pt(Loc loc, const Chan &c)
    {
        if (c.vert) {
            Box b = sm_box(loc.x, loc.y, sm_of_v(c.line));
            return {vx(loc.x, c.line), c.dy < 0 ? b.y0 : b.y1};
        }
        Box b = sm_box(loc.x, loc.y, sm_of_h(loc.y, c.line));
        return {c.dx < 0 ? b.x0 : b.x1, hy(loc.y, c.line)};
    }

    // --- CLB geometry ---
    // Columns (x): pins A/D, rails of the inputs, multiplexers of the LUTs, LUTs, distributors F/FG/G,
    // multiplexers of the storage element, storage element, output rails, output multiplexers
    static constexpr float CLB_X0 = 0.384, CLB_X1 = 0.955; // frame
    static constexpr float D_PIN_X = 0.358, A_PIN_X = 0.371; // D from below, A from above
    static constexpr float QL_X = 0.396, D_X = 0.407, C_X = 0.418, B_X = 0.429, A_X = 0.44, K_END_X = 0.448;
    static constexpr float MUX_X = 0.454, FMUX_X = 0.678, OMUX_X = 0.886, MUX_W = 0.03, MUX_STEP = 0.013,
                           MUX_SLANT = 0.005;
    static constexpr float FGF_X0 = 0.492, BOX_X0 = 0.502, BOX_X1 = 0.57, TAP_X = 0.582;
    static constexpr float M_X0 = 0.594, M_X1 = 0.616, FGF_X1 = 0.628;
    static constexpr float FF_X0 = 0.726, FF_X1 = 0.814, FF_PIN_X = 0.77;
    static constexpr float X_DN_X = 0.93, X_UP_X = 0.942; // direct connections from X down/up
    // ... and their branches in the neighbouring tile: to A and B of the CLB below, to D and C of the CLB above
    static constexpr float XT_A_Y = 0.31, XT_B_Y = 0.335, XB_D_Y = 0.975, XB_C_Y = 0.965;
    // Direct lines in the channel: X from above/below or pad on the track of col.x, Y from the left on local.6
    static constexpr float DIR_X = 0.336, YL_X = 0.212;
    // Rows (y)
    static constexpr float A_ROW = 0.392, B_ROW = 0.476, C_ROW = 0.523; // inputs from the left
    static constexpr float C_LINE = 0.792, K_LINE = 0.805, D_ROW = 0.866; // below the logic to the FF
    static constexpr float F_TOP = 0.45, G_TOP = 0.61, LUT_H = 0.146;
    static constexpr float FGF_Y0 = 0.442, FGF_Y1 = 0.764; // FG frame
    static constexpr float M_Y0 = 0.56, M_Y1 = 0.646, M_IN_F = 0.577, M_IN_G = 0.629; // F/G multiplexer
    static constexpr float M_SEL_X = (M_X0 + M_X1) / 2, SEL_Y = 0.774;
    static constexpr float FF_Y0 = 0.54, FF_Y1 = 0.826;
    static constexpr float F_ROW = 0.45, FG_ROW = 0.463, G_ROW = 0.476; // F, FG, G above the FF to the right
    static constexpr float Q_RAIL = 0.905;                              // Q below everything back to the left
    static constexpr float X_MUX_Y = 0.379, Y_MUX_Y = 0.4675;
    static constexpr float X_Y = X_MUX_Y + 2.5 * MUX_STEP, Y_Y = Y_MUX_Y + 2.5 * MUX_STEP; // outputs X, Y

    enum Col
    {
        COL_LUT, // inputs of the LUTs
        COL_FF,  // inputs of the storage element
        COL_OUT, // outputs X, Y
    };
    // Rail or distributor at which a source is tapped for a multiplexer column
    static float src_x(Col col, int32_t id)
    {
        if (col == COL_OUT) {
            switch (id) {
            case GFX_WIRE_F_O:
                return 0.832;
            case GFX_WIRE_FG_O:
                return 0.844;
            case GFX_WIRE_G_O:
                return 0.856;
            default:
                return 0.868; // Q
            }
        }
        switch (id) {
        case GFX_WIRE_A:
            return A_X;
        case GFX_WIRE_B:
            return B_X;
        case GFX_WIRE_C:
            return C_X;
        case GFX_WIRE_D:
            return D_X;
        case GFX_WIRE_K:
            return K_END_X;
        case GFX_WIRE_Q:
            return QL_X;
        case GFX_WIRE_F_O:
            return 0.64;
        case GFX_WIRE_FG_O:
            return 0.652;
        case GFX_WIRE_G_O:
            return 0.664;
        }
        return -1;
    }
    static float row_y(int32_t id) { return id == GFX_WIRE_F_O ? F_ROW : id == GFX_WIRE_FG_O ? FG_ROW : G_ROW; }

    // Multiplexer: driven line, column, position, inputs from top to bottom
    struct Mux
    {
        int32_t out;
        Col col;
        float y_top;
        int n;
        int32_t in[4];
    };
    static constexpr Mux MUXES[] = {
            {GFX_WIRE_F_I0, COL_LUT, F_TOP, 2, {GFX_WIRE_A, GFX_WIRE_B}},
            {GFX_WIRE_F_I1, COL_LUT, F_TOP + 0.047f, 2, {GFX_WIRE_B, GFX_WIRE_C}},
            {GFX_WIRE_F_I2, COL_LUT, F_TOP + 0.094f, 3, {GFX_WIRE_C, GFX_WIRE_D, GFX_WIRE_Q}},
            {GFX_WIRE_G_I0, COL_LUT, G_TOP, 2, {GFX_WIRE_A, GFX_WIRE_B}},
            {GFX_WIRE_G_I1, COL_LUT, G_TOP + 0.047f, 2, {GFX_WIRE_B, GFX_WIRE_C}},
            {GFX_WIRE_G_I2, COL_LUT, G_TOP + 0.094f, 3, {GFX_WIRE_C, GFX_WIRE_D, GFX_WIRE_Q}},
            {GFX_WIRE_FF_S, COL_FF, A_ROW - MUX_STEP, 3, {GFX_WIRE_A, GFX_WIRE_F_O, GFX_WIRE_FG_O}},
            {GFX_WIRE_FF_D, COL_FF, 0.56, 2, {GFX_WIRE_F_O, GFX_WIRE_FG_O}},
            {GFX_WIRE_FF_CLK, COL_FF, C_LINE - 3 * MUX_STEP, 4, {GFX_WIRE_G_O, GFX_WIRE_FG_O, GFX_WIRE_C, GFX_WIRE_K}},
            {GFX_WIRE_FF_R, COL_FF, D_ROW - 3 * MUX_STEP, 3, {GFX_WIRE_G_O, GFX_WIRE_FG_O, GFX_WIRE_D}},
            {GFX_WIRE_X, COL_OUT, X_MUX_Y, 4, {GFX_WIRE_F_O, GFX_WIRE_FG_O, GFX_WIRE_G_O, GFX_WIRE_Q}},
            {GFX_WIRE_Y, COL_OUT, Y_MUX_Y, 4, {GFX_WIRE_G_O, GFX_WIRE_FG_O, GFX_WIRE_F_O, GFX_WIRE_Q}},
    };
    static constexpr int MUX_FF_CLK = 8;
    // Multiplexers driving a line. FG occupies F and G, its inputs are connected to both.
    template <typename Fn> static bool for_muxes(int32_t id, Fn fn)
    {
        if (id >= GFX_WIRE_FG_I0 && id <= GFX_WIRE_FG_I2) {
            fn(MUXES[id - GFX_WIRE_FG_I0]);
            fn(MUXES[3 + id - GFX_WIRE_FG_I0]);
            return true;
        }
        bool found = false;
        for (auto &m : MUXES)
            if (m.out == id)
                fn(m), found = true;
        return found;
    }
    static float mux_x(const Mux &m) { return m.col == COL_LUT ? MUX_X : m.col == COL_FF ? FMUX_X : OMUX_X; }
    static float mux_in_y(const Mux &m, int k) { return m.y_top + MUX_STEP * (k + 1); }
    static float mux_bot(const Mux &m) { return m.y_top + MUX_STEP * (m.n + 1); }
    static float mux_out_y(const Mux &m) { return (m.y_top + mux_bot(m)) / 2; }
    // topmost and bottommost tap of a source: in the columns LUT/FF or at the outputs
    static void taps(int32_t id, bool out_col, float &top, float &bot)
    {
        top = 2, bot = -1;
        for (auto &m : MUXES) {
            if ((m.col == COL_OUT) != out_col)
                continue;
            for (int k = 0; k < m.n; k++)
                if (m.in[k] == id)
                    top = std::min(top, mux_in_y(m, k)), bot = std::max(bot, mux_in_y(m, k));
        }
    }

    void draw_mux(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float x0, float yt,
                  float x1, float yb) const
    {
        poly(g, style, loc, {{x0, yt}, {x1, yt + MUX_SLANT}, {x1, yb - MUX_SLANT}, {x0, yb}, {x0, yt}});
    }
    // Junction dot on a rail
    void dot(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float x, float y) const
    {
        const float r = 0.0025;
        box(g, style, loc.x + x - r, loc.y + y - r, loc.x + x + r, loc.y + y + r);
        poly(g, style, loc, {{x - r, y - r}, {x + r, y + r}});
        poly(g, style, loc, {{x - r, y + r}, {x + r, y - r}});
    }

    // Output of F, G, FG or of the storage element
    static std::pair<float, float> source_point(int32_t id)
    {
        switch (id) {
        case GFX_WIRE_F_O:
            return {BOX_X1, F_TOP + LUT_H / 2};
        case GFX_WIRE_G_O:
            return {BOX_X1, G_TOP + LUT_H / 2};
        case GFX_WIRE_FG_O:
            return {M_X1, (M_Y0 + M_Y1) / 2};
        default:
            return {FF_X1, (FF_Y0 + FF_Y1) / 2}; // Q
        }
    }

    // Side of an IO tile: 'T'op, 'B'ottom, 'L'eft, 'R'ight
    static char io_side(Loc loc)
    {
        if (loc.y == 0)
            return 'T';
        if (loc.y == LAST)
            return 'B';
        return loc.x == 0 ? 'L' : 'R';
    }

    // Repowering buffers at the boundaries of the 9 sections (datasheet, xc2064db.graph): on the single-length
    // segments running across rows D and G or columns D and G, just before their channel (in Shirriff's drawing
    // between io3 and local.0 or clbw3 and local.1). Two triangles tip to tip: it drives in one of the two
    // directions; which one follows from the routing.
    static constexpr float BUF_D = 0.011, BUF_W = 0.005, BUF_L = 0.007;
    static bool buffered_segment(int k) { return k == 3 || k == 6; } // pieces @C and @F
    void bidi_buffer(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, bool vert, float along,
                     float across) const
    {
        for (float s : {-1.0f, 1.0f}) {
            if (vert)
                poly(g, style, loc,
                     {{across - BUF_W, along + s * BUF_L}, {across + BUF_W, along + s * BUF_L}, {across, along},
                      {across - BUF_W, along + s * BUF_L}});
            else
                poly(g, style, loc,
                     {{along + s * BUF_L, across - BUF_W}, {along + s * BUF_L, across + BUF_W}, {along, across},
                      {along + s * BUF_L, across - BUF_W}});
        }
    }

    // Draw the own piece of a channel line (the whole line up to the pips; neighbouring pieces draw nothing)
    void draw_channel(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Chan &c) const
    {
        const int x = loc.x, y = loc.y;
        if (c.vert) {
            float px = vx(x, c.line);
            if (px < 0)
                return;
            if (c.line <= V_LOC5 && buffered_segment(y))
                bidi_buffer(g, style, loc, true, 1 + BUF_D, px);
            if (c.line <= V_LOC4) { // single-length segment: from matrix to matrix (at the edge into the edge channel)
                float y0 = tile_has_sm(x, y) ? sm_box(x, y, sm_of_v(c.line)).y1 : 0.0f;
                float y1 = tile_has_sm(x, y + 1) ? 1 + sm_box(x, y + 1, sm_of_v(c.line)).y0 : 1.36f;
                poly(g, style, loc, {{px, y0}, {px, y1}});
            } else if (c.line == V_LOC5) { // fifth line: junction, track local.6, jog, local.5
                float end = 1 + (y + 1 >= LAST ? hy(LAST, H_LOC3) : hy(y + 1, H_LOC4)) + 0.015f;
                if (y == 1) {
                    poly(g, style, loc, {{px, hy(1, H_LOC1)}, {px, end}});
                } else {
                    float j = hy(y, H_LOC0), p6 = vx(x, V_LOC6), jog = hy(y, H_LOC5) + 0.03f;
                    poly(g, style, loc, {{px, j}, {p6, j}, {p6, jog}, {px, jog}, {px, end}});
                }
            } else { // Long Line, GCLK: over the whole height, at the edge into the edge channel
                float y0 = y == 1 ? hy(1, H_CLK) : 0.0f, y1 = y == LAST ? hy(LAST, H_CLK) + 0.02f : 1.0f;
                poly(g, style, loc, {{px, y0}, {px, y1}});
                if (c.line == V_CLK && y == 1) // CLK.AA.O: from the clock buffer top left to all columns; in AA
                                               // from local.3 on (input of the GCLK buffer, crosses local.3, long.3)
                    poly(g, style, loc, {{x == 1 ? vx(1, V_LOC3) : 0.0f, hy(1, H_CLK)}, {1.0f, hy(1, H_CLK)}});
            }
        } else {
            float py = hy(y, c.line);
            if (py < 0)
                return;
            if (c.line >= H_LOC1 && c.line <= H_LOC5 && buffered_segment(x))
                bidi_buffer(g, style, loc, false, 1 + BUF_D, py);
            if (c.line >= H_LOC1 && c.line <= H_LOC5) {
                float x0 = tile_has_sm(x, y) ? sm_box(x, y, sm_of_h(y, c.line)).x1 : 0.0f;
                float x1 = tile_has_sm(x + 1, y) ? 1 + sm_box(x + 1, y, sm_of_h(y, c.line)).x0 : 1.36f;
                poly(g, style, loc, {{x0, py}, {x1, py}});
            } else { // Long Line, ACLK
                float x0 = x == 1 ? vx(1, V_LONG2) : 0.0f, x1 = x == LAST ? aclk_end() : 1.0f;
                poly(g, style, loc, {{x0, py}, {x1, py}});
                if (c.line == H_CLK && x == LAST) // input of the ACLK buffer: crosses row.I.long.1 and local.1-4
                    poly(g, style, loc, {{x1, py}, {x1, hy(LAST, H_LONG1)}});
            }
        }
    }

    // --- IOB geometry ---
    // An IOB lies outside next to the channel parallel to the edge: top/bottom next to the horizontal channel of
    // the first or last row, left/right next to the vertical one of the first or last column. Next to each edge
    // CLB there are up to two IOBs: the first pad of its pad tile (z = 0) in the first half, the second pad of the
    // following tile (z = 1) in the second.
    // Coordinates: r along the edge from the start of the IOB, d inwards from the chip edge. Structure as in the
    // datasheet, from outside to inside: pad; output driver (triangle towards the pad) and input driver (triangle
    // pointing inwards); multiplexers for the output (Bel pin I, "O" in the datasheet) and the tristate T; then the
    // lines of output, T and input (Bel pin O, "I" in the datasheet) run across the channel parallel to the edge.
    // As in Shirriff's drawing (iob.js: pin lines io1-io6, x, clbl, clbr), beyond the channel a pin bends into a
    // stub parallel to the edge, which crosses the lines running perpendicular to the edge.
    // Which lines a pin can switch follows from the pips of the chip (xc2064db.graph); the drawing looks them up
    // there and puts a box at each crossing, as in the channel.
    // Direct connections: X (on the right also Y) of the edge CLB runs into the output multiplexer (top/bottom the
    // second IOB is mirrored for this, on the right the path to the second IOB jogs before the edge channel); the
    // input from the pad continues on its stub at the top, bottom and left to A/B, D/C or B of the edge CLB
    // (top/bottom with a branch on the track of col.x).
    static constexpr float IOB_U0 = 0.385, IOB_DU = 0.3135, IOB_W = 0.27; // position at the channel piece, width
    static constexpr float IOB_D0 = 0.18, IOB_D1 = 0.58;                 // frame
    static constexpr float PAD_R = 0.135, PAD_HW = 0.04, PAD_D0 = 0.03, PAD_D1 = 0.11, JCT_D = 0.22;
    static constexpr float OB_R = 0.07, OB_TIP = 0.28, OB_BASE = 0.36;  // output driver
    static constexpr float IB_R = 0.235, IB_BASE = 0.26, IB_TIP = 0.34; // input driver
    static constexpr float OM_R0 = 0.012, OM_R1 = 0.13, TM_R0 = 0.15, TM_R1 = 0.20; // multiplexers
    static constexpr float MX_D0 = 0.44, OM_D1 = 0.52, TM_D1 = 0.50, EN_D = 0.32;
    static constexpr float O_R = 0.07, T_R = 0.175, I_R = IB_R; // lines across the channel
    static constexpr float PIN_R[3] = {O_R, I_R, T_R};          // Bel pins I, O, T (order of the graphics IDs)
    static constexpr float DX_R = 0.0265, DY_R = 0.115;         // X, Y direct (right edge, z = 0)
    static constexpr float DX1_R = 0.025, DY1_R = 0.045;        // ... z = 1, before the output
    static constexpr float JOG_X = 0.98, JOG_Y = 0.97;          // jog towards it, before the edge channel
    // Stubs: on the left on Shirriff's tracks col.A.local.5, io1, io2, io3, elsewhere in steps behind the channel
    // (at the top/bottom/right there is less room there than in Shirriff's drawing)
    static constexpr float STUB_STEP = 0.011;
    static constexpr float L_STUB[4] = {0.234, 0.270, 0.294, 0.318};
    // Input as in the datasheet (Figure 3): after the input driver directly (left) or via the FF (right) into the
    // input multiplexer, whose output is the line of the input (Bel pin O); the clock K of the FF comes from the
    // clock line of the side, outside next to the IOB
    static constexpr float IN_J_D = 0.36, IN_D_R = 0.214, IN_Q_R = 0.243;          // branch, paths
    static constexpr float FF_R0 = 0.224, FF_R1 = 0.262, FF_D0 = 0.385, FF_D1 = 0.455, FF_K_D = 0.43; // FF
    static constexpr float IM_R0 = 0.206, IM_R1 = 0.252, IM_D1 = 0.49, IM_D0 = 0.53; // input multiplexer
    static constexpr float K_R = 0.278;                                             // K outside next to the IOB
    // Clock line per side at the very outside (CLK_EDGE_D from the chip edge). The K mux of the side sits at a
    // corner: top and right in tile AI (top on the track of col.I.local.0 left of column I, right on row.A.local.5
    // below the channel of row A), bottom and left in IA (bottom col.A.local.5, left row.I.local.0 below the
    // channel of row I); its sources cross the stub with boxes.
    static constexpr float CLK_EDGE_D = 0.012;
    static constexpr float KT_X = 0.022, KT_Y1 = 0.307, KR_Y = 0.362, KR_X0 = 0.064;
    static constexpr float KB_X = 0.234, KB_Y0 = 0.034, KL_Y = 0.345, KL_X1 = 0.216;

    struct Iob
    {
        char side;
        float u0;    // start along the edge, in the own tile
        float off;   // top/left the channel lies in the neighbouring tile: IOB moved closer to it
        bool mirror; // top/bottom the second IOB: output multiplexer towards the direct line from X
    };
    static Iob iob(Loc loc, int z)
    {
        char s = io_side(loc);
        return Iob{s, z ? IOB_U0 + IOB_DU - 1 : IOB_U0, (s == 'T' || s == 'L') ? 0.30f : 0.0f,
                   (s == 'T' || s == 'B') && z == 1};
    }
    // Point (u along the edge, d from the chip edge) in tile coordinates of the pad tile
    static std::pair<float, float> edge_pt(char side, float u, float d)
    {
        switch (side) {
        case 'T':
            return {u, d};
        case 'B':
            return {u, 1 - d};
        case 'L':
            return {d, u};
        default:
            return {1 - d, u};
        }
    }
    // u to r in the IOB and vice versa
    static float pin_u(const Iob &b, float r) { return b.mirror ? b.u0 + IOB_W - r : b.u0 + r; }
    static float iob_r(const Iob &b, float u) { return b.mirror ? IOB_W - (u - b.u0) : u - b.u0; }
    // Point in the IOB (d without offset) in tile coordinates
    static std::pair<float, float> iob_pt(const Iob &b, float r, float d)
    {
        return edge_pt(b.side, pin_u(b, r), d + b.off);
    }
    // Depth of the stub of the output (input = false) or input of an IOB. The pins of an IOB do not cross each
    // other: the pin farther away from the lines perpendicular to the edge lies deeper.
    static float stub_d(char side, int z, bool input)
    {
        static constexpr int RANK[4][2][2] = {
                {{2, 3}, {0, 1}}, // top: z = 0 (lines to its left), z = 1 (to its right)
                {{2, 3}, {0, 1}}, // bottom
                {{0, 1}, {2, 3}}, // left: z = 0 (lines above it), z = 1 (below it)
                {{0, 1}, {3, 2}}, // right
        };
        int rank = RANK[side == 'T' ? 0 : side == 'B' ? 1 : side == 'L' ? 2 : 3][z][input];
        switch (side) {
        case 'T':
            return 1 + hy(1, H_LONG3) + STUB_STEP * (rank + 1);
        case 'B':
            return 1 - hy(LAST, H_LONG1) + STUB_STEP * (rank + 1);
        case 'L':
            return 1 + L_STUB[rank];
        default:
            return 1 - vx(LAST, V_LONG1) + STUB_STEP * (rank + 1);
        }
    }
    // r at which X or Y of an edge CLB runs directly into the output multiplexer
    static float direct_r(const Iob &b, int z, bool y)
    {
        if (b.side == 'R')
            return z ? (y ? DY1_R : DX1_R) : (y ? DY_R : DX_R);
        return iob_r(b, (b.side == 'T' ? X_UP_X : X_DN_X) - 1); // X of the edge CLB to the left
    }

    struct IobPip
    {
        float u, d;
        bool cross; // crossing with the stub (line perpendicular to the edge)
    };
    // Position of the pip between pin p (0: I, 1: O, 2: T) of IOB z and the line other (graphics ID in the pad
    // tile). false: no box (X/Y direct).
    static bool iob_pip(Loc loc, int z, int p, int32_t other, IobPip &res)
    {
        Iob b = iob(loc, z);
        float u = pin_u(b, PIN_R[p]);
        if (other == GFX_WIRE_GCLK) { // P9: CLK.AA.O above row A (output mux and clock buffer)
            res = b.side == 'T' ? IobPip{u, 1 + hy(1, H_CLK), false}
                                : IobPip{u, 1 + vx(1, V_CLK), false}; // P11 (left): col.A.clk
            return true;
        }
        if (other == GFX_WIRE_ACLK) { // P43: row.I.clk
            res = b.side == 'B' ? IobPip{u, 1 - hy(LAST, H_CLK), false}
                                : IobPip{1 + hy(LAST, H_CLK), stub_d(b.side, z, true), true}; // P46 (right)
            return true;
        }
        Chan c = chan(other);
        if (!c.ok)
            return false;
        float pos = c.vert ? chan_x(loc, c, -1) : chan_y(loc, c);
        if (c.vert == (b.side == 'L' || b.side == 'R')) // parallel to the edge: crosses the pin itself
            res = {u, (b.side == 'T' || b.side == 'L') ? pos : 1 - pos, false};
        else
            res = {pos, stub_d(b.side, z, p == 1), true};
        return true;
    }

    void iob_line(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Iob &b,
                  std::initializer_list<std::pair<float, float>> rd) const
    {
        bool first = true;
        std::pair<float, float> prev;
        for (auto &p : rd) {
            auto q = iob_pt(b, p.first, p.second);
            if (!first)
                line(g, style, loc.x + prev.first, loc.y + prev.second, loc.x + q.first, loc.y + q.second);
            prev = q, first = false;
        }
    }
    void iob_box(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Iob &b, float r0,
                 float d0, float r1, float d1) const
    {
        auto a = iob_pt(b, r0, d0), c = iob_pt(b, r1, d1);
        box(g, style, loc.x + std::min(a.first, c.first), loc.y + std::min(a.second, c.second),
            loc.x + std::max(a.first, c.first), loc.y + std::max(a.second, c.second));
    }
    // Multiplexer: inputs on the channel side (d1), output towards the pad (d0)
    void iob_mux(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Iob &b, float r0,
                 float r1, float d0, float d1) const
    {
        const float sl = 0.01;
        iob_line(g, style, loc, b, {{r0, d1}, {r1, d1}, {r1 - sl, d0}, {r0 + sl, d0}, {r0, d1}});
    }
    void iob_dot(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Iob &b, float r,
                 float d) const
    {
        auto q = iob_pt(b, r, d);
        dot(g, style, loc, q.first, q.second);
    }

    // --- Wires and nodes from the chip database (for drawing the IOBs) ---
    int32_t wire_gfx(WireId w) const { return chip_tile_info(ctx->chip_info, w.tile).wires[w.index].tile_wire; }
    // Node of the wire with graphics ID gfx in tile loc, WireId() if it does not exist there
    WireId tile_wire(Loc loc, int32_t gfx) const
    {
        int tile = tile_by_xy(ctx->chip_info, loc.x, loc.y);
        const auto &wires = chip_tile_info(ctx->chip_info, tile).wires;
        for (int i = 0; i < wires.ssize(); i++)
            if (wires[i].tile_wire == gfx)
                return ctx->normalise_wire(tile, i);
        return WireId();
    }
    // all wires of a node: fn(tile, graphics ID)
    template <typename Fn> void node_wires(WireId node, Fn fn) const
    {
        for (WireId tw : ctx->get_tile_wire_range(node)) {
            Loc l;
            tile_xy(ctx->chip_info, tw.tile, l.x, l.y);
            fn(l, wire_gfx(tw));
        }
    }
    // Does the node of wire gfx in loc also contain wire target in tile (tx, ty)?
    bool reaches(Loc loc, int32_t gfx, int tx, int ty, int32_t target) const
    {
        WireId w = tile_wire(loc, gfx);
        bool found = false;
        if (w != WireId())
            node_wires(w, [&](Loc l, int32_t id) { found |= l.x == tx && l.y == ty && id == target; });
        return found;
    }
    // Position of the stub of the pad whose input leads directly into tile clb via PT, PB or PL, in that tile's
    // coordinates (top/bottom y, left x)
    float pad_stub(WireId pad, Loc clb) const
    {
        float res = 0;
        node_wires(pad, [&](Loc l, int32_t id) {
            if (id != GFX_WIRE_IO0_O && id != GFX_WIRE_IO1_O)
                return;
            char side = io_side(l);
            auto pt = edge_pt(side, 0, stub_d(side, id == GFX_WIRE_IO1_O, true));
            res = side == 'L' ? pt.first + l.x - clb.x : pt.second + l.y - clb.y;
        });
        return res;
    }

    // Line of an IOB pin: from the multiplexer or input driver across the channel parallel to the edge up to its
    // last crossing or to the stub, which reaches the lines perpendicular to the edge and, for the input, the
    // direct inputs of the edge CLB
    void draw_iob_pin(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, int z, int p) const
    {
        Iob b = iob(loc, z);
        const float u = pin_u(b, PIN_R[p]), ds = stub_d(b.side, z, p == 1);
        float d_end = 0, lo = u, hi = u, branch = -1, branch_d = 0;
        bool stub = false;
        WireId w = tile_wire(loc, GFX_WIRE_IO0_I + 3 * z + p);
        if (w == WireId())
            return;
        auto visit = [&](PipId pip, WireId other) {
            Loc pl = ctx->getPipLocation(pip);
            IobPip q;
            if (pl.x != loc.x || pl.y != loc.y || !iob_pip(loc, z, p, local_gfx_id(other, loc, -1), q))
                return;
            if (q.cross)
                stub = true, lo = std::min(lo, q.u), hi = std::max(hi, q.u);
            else
                d_end = std::max(d_end, q.d);
        };
        if (p == 1) {
            for (PipId pip : ctx->getPipsDownhill(w))
                visit(pip, ctx->getPipDstWire(pip));
            // directly into the edge CLB: top to A (box on the stub) and B, bottom to D and C (branch on the track
            // of col.x), left to B
            node_wires(w, [&](Loc l, int32_t id) {
                if (id == GFX_WIRE_PT || id == GFX_WIRE_PB) {
                    branch = l.x - loc.x + DIR_X, stub = true;
                    branch_d = id == GFX_WIRE_PT ? 1 + B_ROW : 2 - C_ROW;
                    lo = std::min(lo, branch), hi = std::max(hi, branch);
                } else if (id == GFX_WIRE_PL) {
                    float t = l.y - loc.y + B_ROW;
                    stub = true, lo = std::min(lo, t), hi = std::max(hi, t);
                }
            });
        } else {
            for (PipId pip : ctx->getPipsUphill(w))
                visit(pip, ctx->getPipSrcWire(pip));
        }
        float de = (stub ? ds : d_end + 0.012f) - b.off;
        if (p == 0) { // output to the pad: multiplexer -> output driver
            iob_mux(g, style, loc, b, OM_R0, OM_R1, MX_D0, OM_D1);
            iob_line(g, style, loc, b, {{O_R, de}, {O_R, OM_D1}});
            iob_line(g, style, loc, b, {{O_R, MX_D0}, {O_R, OB_BASE}});
        } else if (p == 2) { // tristate: multiplexer -> enable of the output driver
            iob_mux(g, style, loc, b, TM_R0, TM_R1, MX_D0, TM_D1);
            iob_line(g, style, loc, b, {{T_R, de}, {T_R, TM_D1}});
            iob_line(g, style, loc, b, {{T_R, MX_D0}, {T_R, EN_D}, {OB_R + 0.015, EN_D}});
        } else { // input from the pad: input multiplexer -> across the channel
            iob_line(g, style, loc, b, {{I_R, IM_D0}, {I_R, de}});
        }
        if (!stub)
            return;
        poly(g, style, loc, {edge_pt(b.side, lo, ds), edge_pt(b.side, hi, ds)});
        auto tee = [&](float t) { // branch in the middle of the stub
            if (t > lo && t < hi) {
                auto q = edge_pt(b.side, t, ds);
                dot(g, style, loc, q.first, q.second);
            }
        };
        tee(u);
        if (branch >= 0) {
            tee(branch);
            poly(g, style, loc, {edge_pt(b.side, branch, ds), edge_pt(b.side, branch, branch_d)});
        }
    }

    // Clock line of the latched inputs of one side: in the pad tiles a piece at the outer edge, in the corner of
    // the K mux (AI: top, right; IA: bottom, left) its stub up across its sources
    void draw_iob_clock(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, char side) const
    {
        const float e = CLK_EDGE_D, f = 1 - CLK_EDGE_D;
        bool corner_tr = loc.x == LAST && loc.y == 1, corner_bl = loc.x == 1 && loc.y == LAST;
        switch (side) {
        case 'T':
            if (corner_tr) // col.I.local.0: from the line at the top to below row.A.long.3
                poly(g, style, loc, {{KT_X, e - 1}, {KT_X, KT_Y1}});
            else // P9 up to the top right corner
                poly(g, style, loc, {{loc.x == 1 ? 0.3f : 0.0f, e}, {loc.x == LAST ? KT_X : 1.0f, e}});
            break;
        case 'R':
            if (corner_tr) // row.A.local.5 below the channel of row A, then down along the edge
                poly(g, style, loc, {{KR_X0, KR_Y}, {f, KR_Y}, {f, 1.0f}});
            else
                poly(g, style, loc, {{f, 0.0f}, {f, 1.0f}});
            break;
        case 'B':
            if (corner_bl) // col.A.local.5 down from the channel of row I, then right along the edge
                poly(g, style, loc, {{KB_X, KB_Y0}, {KB_X, f}, {1.0f, f}});
            else if (loc.x < LAST) // the IOBs of tile LAST (P43) lie to the left of it
                poly(g, style, loc, {{0.0f, f}, {1.0f, f}});
            break;
        default:
            if (corner_bl) // down along the edge to below the channel of row I, row.I.local.0 to the right
                poly(g, style, loc, {{e - 1, 0.0f}, {e - 1, KL_Y}, {KL_X1, KL_Y}});
            else // at the top up to the second IOB of the first tile (P11)
                poly(g, style, loc, {{e, loc.y == 2 ? -0.05f : 0.0f}, {e, 1.0f}});
            break;
        }
    }

    // Box of a K mux: crossing of its stub with the source (top GCLK: CLK.AA.O ends at the tile edge before it,
    // extended here up to the stub)
    void draw_kmux_pip(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, char side,
                       int32_t src_id, const Chan &cs) const
    {
        switch (side) {
        case 'T':
            if (src_id == GFX_WIRE_GCLK) {
                poly(g, style, loc, {{0.0f, hy(1, H_CLK)}, {KT_X, hy(1, H_CLK)}});
                pip_box(g, style, loc, KT_X, hy(1, H_CLK));
            } else if (cs.ok) {
                pip_box(g, style, loc, KT_X, chan_y(loc, cs));
            }
            break;
        case 'R':
            if (cs.ok)
                pip_box(g, style, loc, chan_x(loc, cs, -1), KR_Y);
            break;
        case 'B':
            if (cs.ok)
                pip_box(g, style, loc, KB_X, chan_y(loc, cs));
            break;
        default:
            if (cs.ok) // also GCLK (col.A.clk)
                pip_box(g, style, loc, chan_x(loc, cs, -1), KL_Y);
            break;
        }
    }

    // X or Y to the right through the channel; in column H through the edge channel into the IOBs that take it
    // directly: z = 0 next to it straight, z = 1 of the tile below via a jog before the edge channel
    void out_right(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float ox, float oy,
                   bool y) const
    {
        if (loc.x < LAST - 1) {
            poly(g, style, loc, {{ox, oy}, {1 + vx(loc.x + 1, y ? V_LONG2 : V_LONG1) + 0.01f, oy}});
            return;
        }
        int32_t id = y ? GFX_WIRE_Y : GFX_WIRE_X;
        bool z0 = reaches(loc, id, LAST, loc.y, y ? GFX_WIRE_IO0_Y : GFX_WIRE_IO0_X);
        bool z1 = loc.y + 1 < LAST && reaches(loc, id, LAST, loc.y + 1, y ? GFX_WIRE_IO1_Y : GFX_WIRE_IO1_X);
        poly(g, style, loc, {{ox, oy}, {z0 ? 2 - OM_D1 : 1 + vx(LAST, V_LONG3) + 0.01f, oy}});
        if (z1) {
            Iob b = iob(Loc(LAST, loc.y + 1, 1), 1);
            float jx = y ? JOG_Y : JOG_X, ty = 1 + pin_u(b, direct_r(b, 1, y));
            poly(g, style, loc, {{jx, oy}, {jx, ty}, {2 - OM_D1, ty}});
            dot(g, style, loc, jx, oy);
        }
    }

    void drawGroup(std::vector<GraphicElement> &g, GroupId group, Loc loc) override
    {
        IdString type = ctx->getGroupType(group);
        if (type == id_SWITCHBOX) {
            Box b = sm_box(loc.x, loc.y, group.index); // SM0 = 8.1, SM1 = 8.2
            box(g, GraphicElement::STYLE_FRAME, loc.x + b.x0, loc.y + b.y0, loc.x + b.x1, loc.y + b.y1);
        } else if (type == id_CLB_FRAME) {
            box(g, GraphicElement::STYLE_FRAME, loc.x + CLB_X0, loc.y + 0.37, loc.x + CLB_X1, loc.y + 0.95);
        }
    }

    void drawBel(std::vector<GraphicElement> &g, GraphicElement::style_t style, IdString bel_type, Loc loc) override
    {
        float x = loc.x, y = loc.y;
        switch (bel_type.index) {
        case id_LUT3.index: { // F on top, G below
            float top = loc.z == Z_F ? F_TOP : G_TOP;
            box(g, style, x + BOX_X0, y + top, x + BOX_X1, y + top + LUT_H);
            break;
        }
        case id_LUT4.index:  // FG: F and G with the F/G multiplexer (B selects) in one frame (one function)
        case id_FGM.index: { // FGM: the same parts without a frame (two functions with their own inputs, B selects)
            float fy = source_point(GFX_WIRE_F_O).second, gy = source_point(GFX_WIRE_G_O).second;
            box(g, style, x + BOX_X0, y + F_TOP, x + BOX_X1, y + F_TOP + LUT_H);
            box(g, style, x + BOX_X0, y + G_TOP, x + BOX_X1, y + G_TOP + LUT_H);
            if (bel_type == id_LUT4)
                poly(g, style, loc,
                     {{FGF_X0, FGF_Y0}, {FGF_X1, FGF_Y0}, {FGF_X1, FGF_Y1}, {FGF_X0, FGF_Y1}, {FGF_X0, FGF_Y0}});
            draw_mux(g, style, loc, M_X0, M_Y0, M_X1, M_Y1);
            poly(g, style, loc, {{BOX_X1, fy}, {TAP_X, fy}, {TAP_X, M_IN_F}, {M_X0, M_IN_F}});
            poly(g, style, loc, {{BOX_X1, gy}, {TAP_X, gy}, {TAP_X, M_IN_G}, {M_X0, M_IN_G}});
            dot(g, style, loc, TAP_X, fy);
            dot(g, style, loc, TAP_X, gy);
            break;
        }
        case id_DFF.index: { // D and clock (with triangle) left, S top, R bottom, Q right
            float cy = mux_out_y(MUXES[MUX_FF_CLK]);
            box(g, style, x + FF_X0, y + FF_Y0, x + FF_X1, y + FF_Y1);
            poly(g, style, loc, {{FF_X0, cy - 0.008}, {FF_X0 + 0.012, cy}, {FF_X0, cy + 0.008}});
            break;
        }
        case id_IOB.index: { // frame, pad, output driver (towards the pad) and input driver (inwards)
            Iob b = iob(loc, loc.z);
            const float ow = 0.03, iw = 0.025;
            iob_line(g, style, loc, b, {{0, IOB_D0}, {IOB_W, IOB_D0}, {IOB_W, IOB_D1}, {0, IOB_D1}, {0, IOB_D0}});
            iob_box(g, style, loc, b, PAD_R - PAD_HW, PAD_D0, PAD_R + PAD_HW, PAD_D1);
            iob_line(g, style, loc, b, {{PAD_R, PAD_D1}, {PAD_R, JCT_D}});
            iob_line(g, style, loc, b, {{OB_R, OB_TIP}, {OB_R, JCT_D}, {IB_R, JCT_D}, {IB_R, IB_BASE}});
            iob_dot(g, style, loc, b, PAD_R, JCT_D);
            iob_line(g, style, loc, b,
                     {{OB_R - ow, OB_BASE}, {OB_R + ow, OB_BASE}, {OB_R, OB_TIP}, {OB_R - ow, OB_BASE}});
            iob_line(g, style, loc, b,
                     {{IB_R - iw, IB_BASE}, {IB_R + iw, IB_BASE}, {IB_R, IB_TIP}, {IB_R - iw, IB_BASE}});
            // Input: directly or via the FF (clock with triangle on the right) into the input multiplexer; if the
            // IOB is occupied, the multiplexer shows the selected path (XC2000_INFF: via the FF)
            iob_line(g, style, loc, b, {{I_R, IB_TIP}, {I_R, IN_J_D}});
            iob_line(g, style, loc, b, {{IN_D_R, IM_D1}, {IN_D_R, IN_J_D}, {IN_Q_R, IN_J_D}, {IN_Q_R, FF_D0}});
            iob_dot(g, style, loc, b, I_R, IN_J_D);
            iob_box(g, style, loc, b, FF_R0, FF_D0, FF_R1, FF_D1);
            iob_line(g, style, loc, b, {{FF_R1, FF_K_D - 0.01f}, {FF_R1 - 0.01f, FF_K_D}, {FF_R1, FF_K_D + 0.01f}});
            iob_line(g, style, loc, b, {{IN_Q_R, FF_D1}, {IN_Q_R, IM_D1}});
            iob_mux(g, style, loc, b, IM_R0, IM_R1, IM_D0, IM_D1);
            if (const CellInfo *ci = ctx->getBoundBelCell(ctx->getBelByLocation(loc)))
                if (ci->type.in(id_XC2000_INBUF, id_XC2000_IOBUF, id_XC2000_INFF))
                    iob_line(g, style, loc, b,
                             {{ci->type == id_XC2000_INFF ? IN_Q_R : IN_D_R, IM_D1}, {I_R, IM_D0}});
            break;
        }
        }
    }

    void drawWire(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, IdString wire_type,
                  int32_t tilewire, IdString tile_type) override
    {

        // CLB: multiplexer with output to the Bel or to the pin
        bool is_mux = for_muxes(tilewire, [&](const Mux &m) {
            float ox = mux_x(m) + MUX_W, oy = mux_out_y(m);
            draw_mux(g, style, loc, mux_x(m), m.y_top, ox, mux_bot(m));
            switch (m.out) {
            case GFX_WIRE_X: // through the right channel to long.1 (column H: into the IOBs on the right), direct lines
                out_right(g, style, loc, ox, oy, false);
                if (loc.y > 1) { // to D and C of the CLB above
                    poly(g, style, loc,
                         {{X_UP_X, oy}, {X_UP_X, XB_C_Y - 1}, {DIR_X, XB_C_Y - 1}, {DIR_X, C_ROW - 1}});
                    poly(g, style, loc, {{X_UP_X, XB_D_Y - 1}, {D_PIN_X, XB_D_Y - 1}});
                    dot(g, style, loc, X_UP_X, oy);
                    dot(g, style, loc, X_UP_X, XB_D_Y - 1);
                } else if (reaches(loc, GFX_WIRE_X, loc.x + 1, 0, GFX_WIRE_IO1_X)) { // into the IOB above
                    poly(g, style, loc, {{X_UP_X, oy}, {X_UP_X, -1 + 0.30f + OM_D1}});
                    dot(g, style, loc, X_UP_X, oy);
                }
                if (loc.y < ctx->getGridDimY() - 2) { // to A and B of the CLB below
                    poly(g, style, loc,
                         {{X_DN_X, oy}, {X_DN_X, 1 + XT_B_Y}, {DIR_X, 1 + XT_B_Y}, {DIR_X, 1 + B_ROW}});
                    poly(g, style, loc, {{X_DN_X, 1 + XT_A_Y}, {A_PIN_X, 1 + XT_A_Y}});
                    dot(g, style, loc, X_DN_X, oy);
                    dot(g, style, loc, X_DN_X, 1 + XT_A_Y);
                } else if (reaches(loc, GFX_WIRE_X, loc.x + 1, LAST, GFX_WIRE_IO1_X)) { // into the IOB below
                    poly(g, style, loc, {{X_DN_X, oy}, {X_DN_X, 2 - OM_D1}});
                    dot(g, style, loc, X_DN_X, oy);
                }
                break;
            case GFX_WIRE_Y: // through the right channel to long.2, branch on local.6 to B of the neighbouring CLB
                out_right(g, style, loc, ox, oy, true);
                if (loc.x < LAST - 1) {
                    poly(g, style, loc, {{1 + YL_X, oy}, {1 + YL_X, B_ROW}});
                    dot(g, style, loc, 1 + YL_X, oy);
                }
                break;
            case GFX_WIRE_FF_S: // set from above
                poly(g, style, loc, {{ox, oy}, {FF_PIN_X, oy}, {FF_PIN_X, FF_Y0}});
                break;
            case GFX_WIRE_FF_R: // reset from below
                poly(g, style, loc, {{ox, oy}, {FF_PIN_X, oy}, {FF_PIN_X, FF_Y1}});
                break;
            default:
                poly(g, style, loc, {{ox, oy}, {m.col == COL_LUT ? BOX_X0 : FF_X0, oy}});
                break;
            }
        });
        if (is_mux)
            return;
        // Branch with a dot if the line continues beyond y
        auto tee = [&](float tx, float ty, float lo, float hi) {
            if (ty > lo && ty < hi)
                dot(g, style, loc, tx, ty);
        };
        float top, bot;
        switch (tilewire) {
        case GFX_WIRE_A: // pin at the top, row from the left
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{A_PIN_X, 0.03}, {A_PIN_X, A_ROW}, {A_X, A_ROW}, {A_X, bot}});
            return;
        case GFX_WIRE_B: // pins on the left
            poly(g, style, loc, {{0.03, B_ROW}, {B_X, B_ROW}, {B_X, SEL_Y}});
            return;
        case GFX_WIRE_C:
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{0.03, C_ROW}, {C_X, C_ROW}, {C_X, bot}});
            return;
        case GFX_WIRE_D: // pin at the bottom (crosses the channel and Long Line below), row from the left
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{D_PIN_X, 1.28}, {D_PIN_X, D_ROW}, {D_X, D_ROW}, {D_X, top}});
            return;
        case GFX_WIRE_K: // from long.2 (column A: long.4, ACLK) and GCLK
            poly(g, style, loc, {{(loc.x == 1 ? vx(1, V_LONG4) : vx(loc.x, V_LONG2)) - 0.005f, K_LINE}, {K_END_X, K_LINE}});
            return;
        case GFX_WIRE_F_O:
        case GFX_WIRE_G_O:
        case GFX_WIRE_FG_O: { // output -> distributor, above the storage element -> output rail
            auto src = source_point(tilewire);
            float fx = src_x(COL_FF, tilewire), rx = src_x(COL_OUT, tilewire), ry = row_y(tilewire), rtop, rbot;
            taps(tilewire, false, top, bot);
            taps(tilewire, true, rtop, rbot);
            top = std::min({top, ry, src.second}), bot = std::max({bot, ry, src.second});
            rtop = std::min(rtop, ry), rbot = std::max(rbot, ry);
            poly(g, style, loc, {src, {fx, src.second}});
            poly(g, style, loc, {{fx, top}, {fx, bot}});
            poly(g, style, loc, {{fx, ry}, {rx, ry}});
            poly(g, style, loc, {{rx, rtop}, {rx, rbot}});
            tee(fx, src.second, top, bot);
            tee(fx, ry, top, bot);
            tee(rx, ry, rtop, rbot);
            return;
        }
        case GFX_WIRE_Q: { // output -> rail on the right (X, Y), around the bottom back to the LUTs
            auto src = source_point(tilewire);
            float rx = src_x(COL_OUT, tilewire), rtop, rbot;
            taps(tilewire, true, rtop, rbot);
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {src, {rx, src.second}});
            poly(g, style, loc, {{rx, rtop}, {rx, Q_RAIL}, {QL_X, Q_RAIL}, {QL_X, top}});
            tee(rx, src.second, rtop, Q_RAIL);
            return;
        }
        case GFX_WIRE_FG_I3: // B selects in the F/G multiplexer
            poly(g, style, loc, {{M_SEL_X, SEL_Y}, {M_SEL_X, M_Y1 - MUX_SLANT / 2}});
            return;
        case GFX_WIRE_XT: // parts of nodes drawn by a neighbouring tile
        case GFX_WIRE_XB:
        case GFX_WIRE_YL:
        case GFX_WIRE_PL:
        case GFX_WIRE_PT:
        case GFX_WIRE_PB:
            return;
        }

        // Clock of the latched inputs: K of an IOB from the clock line at the outer edge to the FF, the clock line
        // of a side (in the corners AI and IA with the stub of its K mux)
        if (tilewire == GFX_WIRE_IO0_K || tilewire == GFX_WIRE_IO1_K) {
            Iob b = iob(loc, tilewire == GFX_WIRE_IO1_K);
            float de = CLK_EDGE_D - b.off;
            iob_line(g, style, loc, b, {{K_R, de}, {K_R, FF_K_D}, {FF_R1, FF_K_D}});
            iob_dot(g, style, loc, b, K_R, de);
            return;
        }
        if (tilewire >= GFX_WIRE_IOCLK_T && tilewire <= GFX_WIRE_IOCLK_L) {
            draw_iob_clock(g, style, loc, "TRBL"[tilewire - GFX_WIRE_IOCLK_T]);
            return;
        }

        // IOB: multiplexers and lines of the pins (clock buffer: P9 or P43 crosses its clock line, the box there is
        // drawn by the pip)
        if (tilewire >= GFX_WIRE_IO0_I && tilewire <= GFX_WIRE_IO1_T) {
            int z = (tilewire - GFX_WIRE_IO0_I) / 3, p = (tilewire - GFX_WIRE_IO0_I) % 3; // I, O, T
            draw_iob_pin(g, style, loc, z, p);
            return;
        }

        // Channels: the own piece draws the whole line, neighbouring pieces (_U, _R, _L, _D, ...) nothing. The
        // pad tiles on the left and at the top only hold accesses to lines of the neighbouring tiles.
        Chan c = chan(tilewire);
        if (c.ok && c.dx == 0 && c.dy == 0 && loc.x > 0 && loc.y > 0)
            draw_channel(g, style, loc, c);
        // Otherwise parts of nodes drawn by other wires (X/Y direct in the IOB)
    }

    // Graphics ID of the wire a node has in tile loc. nextpnr passes drawPip the graphics ID of the canonical
    // node wire, which may lie in another tile.
    int32_t local_gfx_id(WireId node, Loc loc, int32_t fallback) const
    {
        int tile = tile_by_xy(ctx->chip_info, loc.x, loc.y);
        for (WireId tw : ctx->get_tile_wire_range(node))
            if (tw.tile == tile)
                return chip_tile_info(ctx->chip_info, tw.tile).wires[tw.index].tile_wire;
        return fallback;
    }

    void drawPip(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, WireId src, IdString src_type,
                 int32_t src_id, WireId dst, IdString dst_type, int32_t dst_id) override
    {
        // nextpnr hides unused pips. Here they are part of the schematic and are drawn dimmed.
        if (style == GraphicElement::STYLE_HIDDEN)
            style = GraphicElement::STYLE_INACTIVE;
        src_id = local_gfx_id(src, loc, src_id);
        dst_id = local_gfx_id(dst, loc, dst_id);

        // Channels: switch matrix (pin to pin), crossing (box), junction of the fifth line
        Chan cs = chan(src_id), cd = chan(dst_id);
        // Input of a clock buffer from a line parallel to the clock line: vertical sources of GCLK cross CLK.AA.O
        // at the top in AA, horizontal ones of ACLK cross its end in II
        if (cs.ok && cd.ok && cs.vert == cd.vert && (dst_id == GFX_WIRE_GCLK || dst_id == GFX_WIRE_ACLK)) {
            if (dst_id == GFX_WIRE_GCLK)
                pip_box(g, style, loc, chan_x(loc, cs, -1), hy(1, H_CLK));
            else
                pip_box(g, style, loc, aclk_end(), chan_y(loc, cs));
            return;
        }
        if (cs.ok && cd.ok) {
            if (sm_line(loc, cs) && sm_line(loc, cd)) {
                auto a = sm_pin_pt(loc, cs), b = sm_pin_pt(loc, cd);
                poly(g, style, loc, {a, b});
            } else if (cs.vert && cd.vert) { // only the fifth line: piece above -> own piece
                pip_box(g, style, loc, vx(loc.x, V_LOC5), hy(loc.y, H_LOC0));
            } else {
                const Chan &v = cs.vert ? cs : cd, &h = cs.vert ? cd : cs;
                pip_box(g, style, loc, chan_x(loc, v, h.line), chan_y(loc, h));
            }
            return;
        }

        // K mux of a side (source -> clock line); fixed from the clock line to K of an IOB (dot, drawn by K)
        if (dst_id >= GFX_WIRE_IOCLK_T && dst_id <= GFX_WIRE_IOCLK_L) {
            draw_kmux_pip(g, style, loc, "TRBL"[dst_id - GFX_WIRE_IOCLK_T], src_id, cs);
            return;
        }
        if (src_id >= GFX_WIRE_IOCLK_T && src_id <= GFX_WIRE_IOCLK_L)
            return;

        // Inside the CLB: tap at rail or distributor -> multiplexer input, when used also on to the output
        bool is_mux = for_muxes(dst_id, [&](const Mux &m) {
            for (int k = 0; k < m.n; k++) {
                if (m.in[k] != src_id)
                    continue;
                float bx = src_x(m.col, src_id), mx = mux_x(m), iy = mux_in_y(m, k);
                dot(g, style, loc, bx, iy);
                poly(g, style, loc, {{bx, iy}, {mx, iy}});
                if (style != GraphicElement::STYLE_INACTIVE)
                    poly(g, style, loc, {{mx, iy}, {mx + MUX_W, mux_out_y(m)}});
            }
        });
        if (is_mux)
            return;
        if (dst_id == GFX_WIRE_FG_I3) { // B -> select of the F/G multiplexer
            poly(g, style, loc, {{B_X, SEL_Y}, {M_SEL_X, SEL_Y}});
            return;
        }

        // Routing -> CLB inputs (mux sources from clb.js)
        switch (dst_id) {
        case GFX_WIRE_A: // pin crosses the channel above
            if (cs.ok)
                pip_box(g, style, loc, A_PIN_X, chan_y(loc, cs));
            else if (src_id == GFX_WIRE_XT) // X of the CLB above
                pip_box(g, style, loc, A_PIN_X, XT_A_Y);
            else if (src_id == GFX_WIRE_PT) // pad at the top: on its stub
                pip_box(g, style, loc, A_PIN_X, pad_stub(src, loc));
            return;
        case GFX_WIRE_B:
        case GFX_WIRE_C: { // rows cross the channel on the left
            float py = dst_id == GFX_WIRE_B ? B_ROW : C_ROW;
            if (cs.ok)
                pip_box(g, style, loc, chan_x(loc, cs, -1), py);
            else if (src_id == GFX_WIRE_XT || src_id == GFX_WIRE_XB || src_id == GFX_WIRE_PT ||
                     src_id == GFX_WIRE_PB) // direct connection from X or pad above/below (col.x)
                pip_box(g, style, loc, DIR_X, py);
            else if (src_id == GFX_WIRE_PL) // direct connection from the pad on the left: on its stub
                pip_box(g, style, loc, pad_stub(src, loc), py);
            else if (src_id == GFX_WIRE_YL) // direct connection from Y of the CLB on the left (local.6)
                pip_box(g, style, loc, YL_X, py);
            return;
        }
        case GFX_WIRE_D: // pin crosses the channel below
            if (cs.ok)
                pip_box(g, style, loc, D_PIN_X, chan_y(loc, cs));
            else if (src_id == GFX_WIRE_XB) // directly from X below
                pip_box(g, style, loc, D_PIN_X, XB_D_Y);
            else if (src_id == GFX_WIRE_PB) // pad below: on its stub
                pip_box(g, style, loc, D_PIN_X, pad_stub(src, loc));
            return;
        case GFX_WIRE_K: // long.2 (column A: long.4) and GCLK
            if (cs.ok)
                pip_box(g, style, loc, chan_x(loc, cs, -1), K_LINE);
            return;
        }
        // CLB outputs -> channel on the right
        if ((src_id == GFX_WIRE_X || src_id == GFX_WIRE_Y) && cd.ok) {
            pip_box(g, style, loc, chan_x(loc, cd, -1), src_id == GFX_WIRE_X ? X_Y : Y_Y);
            return;
        }

        // IOB: box where a pin or its stub crosses a line (for the clock buffer the clock line); X/Y directly at
        // the input of the output multiplexer
        int32_t pin = (src_id >= GFX_WIRE_IO0_I && src_id <= GFX_WIRE_IO1_T) ? src_id : dst_id;
        if (pin < GFX_WIRE_IO0_I || pin > GFX_WIRE_IO1_T)
            return;
        int z = (pin - GFX_WIRE_IO0_I) / 3, p = (pin - GFX_WIRE_IO0_I) % 3;
        int32_t other = pin == src_id ? dst_id : src_id;
        Iob b = iob(loc, z);
        if (other >= GFX_WIRE_IO0_X && other <= GFX_WIRE_IO1_Y) {
            bool y = other == GFX_WIRE_IO0_Y || other == GFX_WIRE_IO1_Y;
            auto q = iob_pt(b, direct_r(b, z, y), OM_D1 + 0.012f);
            pip_box(g, style, loc, q.first, q.second);
            return;
        }
        IobPip q;
        if (iob_pip(loc, z, p, other, q)) {
            auto pt = edge_pt(b.side, q.u, q.d);
            pip_box(g, style, loc, pt.first, pt.second);
        }
    }
};

struct Xc2064Arch : HimbaechelArch
{
    Xc2064Arch() : HimbaechelArch("xc2064") {};
    bool match_device(const std::string &device) override
    {
        std::string d = device;
        for (auto &c : d)
            c = std::toupper(static_cast<unsigned char>(c));
        return d == "XC2064" || d == "XC2064-50" || d == "XC2064-70" || d == "XC2064-100" || d == "XC2064-130";
    }
    std::unique_ptr<HimbaechelAPI> create(const std::string &device) override
    {
        return std::make_unique<Xc2064Impl>();
    }
} xc2064Arch;

} // namespace

NEXTPNR_NAMESPACE_END
