/*
 *  nextpnr-himbaechel uarch "xc2064": Modell des Xilinx XC2064 (1985, das erste FPGA).
 *  Fabric-Beschreibung: xc2064_arch_gen.py. Aufbau übernommen von der upstream-uarch "example"
 *  (Copyright (C) 2023 gatecat <gatecat@ds0.me>, ISC-Lizenz).
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
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

// z-Positionen der Bels einer CLB-Kachel (siehe xc2064_arch_gen.py)
enum ClbZ
{
    Z_F = 0,  // LUT3: Funktion F von 3 Variablen
    Z_G = 1,  // LUT3: Funktion G von 3 Variablen
    Z_FG = 2, // LUT4: F und G als eine Funktion von 4 Variablen
    Z_FF = 3, // DFF: Flipflop oder Latch
};

// Signalquellen innerhalb einer CLB (für die Zuordnung der Eingangsmultiplexer)
enum Src
{
    S_A = 0, // CLB-Eingänge A-D: jeder führt genau ein Netz
    S_B,
    S_C,
    S_D,
    S_Q, // FF-Ausgang dieser CLB
    S_F, // Ausgang F bzw. FG dieser CLB
    S_G, // Ausgang G bzw. FG dieser CLB
    S_K, // Takteingang K (nur globale Taktnetze)
    S_COUNT
};
constexpr uint8_t M(Src s) { return uint8_t(1u << s); }

// Eingangsmultiplexer laut Shirriffs Bitstream-Decoder (clb.js)
constexpr uint8_t LUT_IN_OPTS[4] = {
        M(S_A) | M(S_B),          // Eingang 1 aus A oder B
        M(S_B) | M(S_C),          // Eingang 2 aus B oder C
        M(S_C) | M(S_D) | M(S_Q), // Eingang 3 aus C, D oder Q
        M(S_B),                   // FG: B wählt zwischen F und G
};

constexpr uint8_t FF_CLK_OPTS = M(S_K) | M(S_C) | M(S_G);
constexpr uint8_t FF_SET_OPTS = M(S_A) | M(S_F);
constexpr uint8_t FF_RES_OPTS = M(S_D) | M(S_G);

// Zusatzdaten eines Pips aus dem Graphen (xc2064_arch_gen.py, PipExtra): die Zeile im Textformat, die ihn
// programmiert, und seine Art
NPNR_PACKED_STRUCT(struct Xc2064PipExtraPOD {
    int32_t cfg;  // IdString der Textzeile
    int32_t kind; // PIP_CFG oder PIP_CLKBUF
});
enum PipKind
{
    PIP_CFG = 1,
    PIP_CLKBUF = 2, // Eingang eines Taktpuffers: Code unbekannt, nur mit --vopt clkbuf
};

struct Xc2064Impl : HimbaechelAPI
{
    ~Xc2064Impl() {};

    po::options_description getUArchOptions()
    {
        po::options_description specific("XC2064 specific options");
        specific.add_options()("pcf", po::value<std::string>(),
                               "PCF file with pin constraints: set_io [-nowarn] <port> <pin> (pins of the package, "
                               "e.g. P9)");
        specific.add_options()("package", po::value<std::string>(), "package: PC68 (default, 58 I/O) or PD48 (40 I/O)");
        specific.add_options()("out", po::value<std::string>(),
                               "write the configuration as text for xc2064pack (format: arch/xc2064/xc2064db/config.py)");
        specific.add_options()("clkbuf", "use the clock buffers GCLK/ACLK (their input codes are unknown, so the "
                                         "result cannot become a bitstream)");
        return specific;
    }

    // Geschwindigkeitsstufe aus dem Gerätenamen wie bei Xilinx: XC2064-50, -70, -100, -130 (Umlaufrate in
    // MHz), ohne Zusatz -70
    void init_database(Arch *arch) override
    {
        init_uarch_constids(arch);
        arch->load_chipdb("xc2064/chipdb-xc2064.bin");
        const std::string &dev = arch->args.device;
        auto dash = dev.find('-');
        arch->set_speed_grade(dash == std::string::npos ? "70" : dev.substr(dash + 1));
        // Gehäuse (xc2064db/packages.py): die IOB-Bels heißen nach dem PLCC68-Pin, PCF und LOC nennen den Pin
        // des gewählten Gehäuses
        auto pkg = arch->args.options.find("package");
        package = pkg == arch->args.options.end() ? "PC68" : pkg->second.as<std::string>();
        if (package != "PC68" && package != "PD48")
            log_error("Unbekanntes Gehäuse '%s' (PC68 oder PD48)\n", package.c_str());
        arch->set_package(package);
    }

    void init(Context *ctx) override
    {
        h.init(ctx);
        HimbaechelAPI::init(ctx);
        // Pads nach Pin des Gehäuses, die bebondeten IOBs und die beiden Taktpins (Bel-Namen P9, P43)
        for (BelId bel : ctx->getBels()) {
            if (ctx->getBelType(bel) != id_IOB)
                continue;
            if (const PadInfoPOD *pad = ctx->get_bel_package_pin(bel)) {
                pad_bels[IdString(pad->package_pin)] = bel;
                bonded.insert(bel);
            }
            IdString name = ctx->getBelName(bel)[1];
            if (name == ctx->id("P9"))
                clock_pads[0] = bel;
            else if (name == ctx->id("P43"))
                clock_pads[1] = bel;
        }
        clkbuf = ctx->args.options.count("clkbuf") > 0;
    }

    // Das Routing des XC2064 ist knapp (4 Spuren je Kanal, 81 Kreuzungen): router2 löst Überlastung
    // zuverlässiger als router1 (wie bei gatemate/xilinx). "--router router1" bleibt möglich.
    std::string getDefaultRouter() const override { return "router2"; }

    // IO-Puffer (alle auf einem IOB): Eingang, Ausgang, Tristate-Ausgang, bidirektional
    static bool is_io_buffer(IdString type)
    {
        return type.in(id_XC2000_INBUF, id_XC2000_OUTBUF, id_XC2000_TOBUF, id_XC2000_IOBUF);
    }

    // IO-Puffer, dessen PAD am Top-Level-Port (Zelle $nextpnr_*buf) hängt
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

    // Pin-Zuordnung aus einer PCF-Datei wie bei iCE40: "set_io [-nowarn] <Port> <Pin>", Busse als
    // name[i]. Setzt LOC am IO-Puffer des Ports und überschreibt damit ein LOC aus dem Verilog.
    void read_pcf(const std::string &file)
    {
        std::ifstream in(file);
        if (!in)
            log_error("PCF-Datei '%s' lässt sich nicht lesen\n", file.c_str());
        log_info("Lese Pin-Zuordnung aus %s\n", file.c_str());
        dict<IdString, std::string> used; // Pin -> Port
        std::string line;
        for (int lineno = 1; std::getline(in, line); lineno++) {
            std::istringstream ss(line.substr(0, line.find('#')));
            std::vector<std::string> w;
            for (std::string t; ss >> t;)
                w.push_back(t);
            if (w.empty())
                continue;
            if (w[0] != "set_io")
                log_error("%s:%d: unbekannter Befehl '%s' (nur set_io)\n", file.c_str(), lineno, w[0].c_str());
            bool nowarn = false;
            size_t i = 1;
            for (; i < w.size() && w[i][0] == '-'; i++) {
                if (w[i] == "-nowarn")
                    nowarn = true;
                else
                    log_warning("%s:%d: Option '%s' wird ignoriert\n", file.c_str(), lineno, w[i].c_str());
            }
            if (i + 2 != w.size())
                log_error("%s:%d: erwartet 'set_io [-nowarn] <Port> <Pin>'\n", file.c_str(), lineno);
            const std::string &port_name = w[i], &pin_name = w[i + 1];
            IdString pin = ctx->id(pin_name);
            if (!pad_bels.count(pin))
                log_error("%s:%d: '%s' ist kein I/O-Pin des Gehäuses %s\n", file.c_str(), lineno, pin_name.c_str(),
                          package.c_str());
            if (used.count(pin))
                log_error("%s:%d: Pin %s ist schon '%s' zugeordnet\n", file.c_str(), lineno, pin_name.c_str(),
                          used.at(pin).c_str());
            CellInfo *port = ctx->getCellForPinConstraint(port_name);
            if (!port) {
                if (!nowarn)
                    log_warning("%s:%d: kein Port '%s' im Design\n", file.c_str(), lineno, port_name.c_str());
                continue;
            }
            CellInfo *buf = io_buffer(port);
            if (!buf)
                log_error("%s:%d: Port '%s' hat keinen IO-Puffer XC2000_*BUF (synth_xc2064 -noiopad?)\n",
                          file.c_str(), lineno, port_name.c_str());
            auto old = buf->attrs.find(id_LOC);
            if (old != buf->attrs.end() && old->second.as_string() != pin_name)
                log_warning("%s:%d: '%s' war per LOC an %s, jetzt an %s\n", file.c_str(), lineno,
                            port_name.c_str(), old->second.as_string().c_str(), pin_name.c_str());
            buf->attrs[id_LOC] = pin_name;
            used[pin] = port_name;
            log_info("    %s -> %s\n", port_name.c_str(), pin_name.c_str());
        }
    }

    // Pins aus PCF bzw. (* LOC="P9" *) am IO-Puffer (XC2000_INBUF usw.): das IOB schon beim Packen fest
    // belegen (wie GateMate), damit die GUI nach "Pack" die belegten Pads zeigt. Ein BEL-Attribut
    // bleibt dabei weg, sonst würde der Placer die Zelle ein zweites Mal binden wollen.
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
                log_error("%s: LOC \"%s\" ist kein I/O-Pin des Gehäuses %s\n", ci->name.c_str(ctx), pin.c_str(ctx),
                          package.c_str());
            BelId bel = pad_bels.at(pin);
            if (!ctx->checkBelAvail(bel))
                log_error("%s: Pad %s ist schon mit %s belegt\n", ci->name.c_str(ctx), pin.c_str(ctx),
                          ctx->nameOf(ctx->getBoundBelCell(bel)));
            ci->attrs.erase(id_BEL);
            ctx->bindBel(bel, ci, STRENGTH_FIXED);
            bound++;
        }
        log_info("Placed %d IO buffers at their constrained pads.\n", bound);
    }

    // Takte ohne Pin-Zuordnung an die Taktpads: Nur von P9 (GCLK) und P43 (ACLK) erreicht ein Takt K
    // aller CLBs, sonst belegt er in jeder CLB einen der Eingänge A-D. Das Netz mit den meisten
    // Speicherelementen bekommt das erste freie Taktpad, das nächste das zweite.
    void bind_clock_pads()
    {
        dict<IdString, int> clk_users; // Netz -> Anzahl Speicherelemente
        for (auto &cell : ctx->cells) {
            const CellInfo *ci = cell.second.get();
            const NetInfo *clk = ci->type == id_XC2000_DFF ? ci->getPort(id_CLK) : nullptr;
            if (clk)
                clk_users[clk->name]++;
        }
        std::vector<std::pair<int, NetInfo *>> clocks;
        for (auto &u : clk_users) {
            NetInfo *net = ctx->nets.at(u.first).get();
            const CellInfo *drv = net->driver.cell;
            if (!is_pad_input(net))
                continue; // abgeleiteter Takt: läuft über das allgemeine Routing
            if (drv->bel != BelId() || drv->attrs.count(id_BEL)) {
                if (!is_global_clock(net))
                    log_info("Clock '%s' (%s) is constrained to a pad without clock buffer, uses CLB inputs.\n",
                             ctx->nameOf(net), storage_elements(u.second).c_str());
                continue;
            }
            clocks.push_back({u.second, net});
        }
        std::stable_sort(clocks.begin(), clocks.end(),
                         [](const auto &a, const auto &b) { return a.first > b.first; });
        auto next = clocks.begin();
        for (int c = 0; c < 2 && next != clocks.end(); c++) {
            BelId pad = clock_pads[c];
            if (!ctx->checkBelAvail(pad) || !bonded.count(pad))
                continue;
            ctx->bindBel(pad, next->second->driver.cell, STRENGTH_FIXED);
            log_info("Clock '%s' (%s) placed at %s (%s).\n", ctx->nameOf(next->second),
                     storage_elements(next->first).c_str(), ctx->getBelName(pad)[1].c_str(ctx),
                     c ? "ACLK" : "GCLK");
            ++next;
        }
        for (; next != clocks.end(); ++next)
            log_info("Clock '%s' (%s): no free clock pad, uses CLB inputs.\n", ctx->nameOf(next->second),
                     storage_elements(next->first).c_str());
    }

    // Konstantes T ist im Original kein Signal, sondern der Modus des IOB (T-Mux "an" bzw. "aus", iob.js):
    // der Routing-Graph hat dafür keine Pips. T = 0 (Treiber immer an) wird zu XC2000_OUTBUF, beim
    // XC2000_IOBUF lesen die Nutzer von O dann direkt I. T = 1 (Treiber aus) wird zu XC2000_INBUF, beim
    // XC2000_TOBUF bleibt das Pad damit ein Eingang ohne Nutzer.
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
                        log_error("%s: Tristate-Puffer mit T = 0, aber ohne Eingang I\n", ctx->nameOf(ci));
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

    // Konstanten: Der XC2064 hat keine Konstanten-Leitung. Ein konstanter LUT-Eingang geht in den LUT-Inhalt
    // (INIT hängt danach nicht mehr von ihm ab, sein Eingangs-Mux bleibt aus), Set/Reset = 0 heißt ohne
    // Set/Reset. Was bleibt (konstanter Ausgang eines Pads, Set/Reset = 1, Takt, ...), treibt eine LUT mit
    // konstantem Inhalt, je Wert eine; ein FF-Dateneingang bekommt eine eigene (D nur aus F/FG der CLB).
    void fold_constants()
    {
        int folded = 0, dropped = 0, luts = 0;
        std::vector<IdString> drivers;
        dict<int, NetInfo *> const_net; // 0/1 -> Netz der gemeinsamen Konstanten-LUT
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
        std::vector<NetInfo *> nets; // vorher sammeln: const_lut legt Netze an
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
                int width = ci->type == id_XC2000_LUT3 ? 3 : ci->type == id_XC2000_LUT4 ? 4 : 0;
                int idx = -1;
                for (int i = 0; i < width; i++)
                    if (u.port == lut_in(i))
                        idx = i;
                ci->disconnectPort(u.port);
                if (idx >= 0) { // LUT-Eingang: Inhalt für den festen Wert auf alle Adressen übertragen
                    uint64_t old_init = uint64_t(ci->params.at(id_INIT).as_int64()), new_init = 0;
                    for (int a = 0; a < (1 << width); a++) {
                        int b = (a & ~(1 << idx)) | (value << idx);
                        if ((old_init >> b) & 1)
                            new_init |= uint64_t(1) << a;
                    }
                    ci->params[id_INIT] = Property(int64_t(new_init), 1 << width);
                    folded++;
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
        if (folded || dropped || luts)
            log_info("Constants: %d LUT inputs folded into INIT, %d set/reset inputs dropped, %d constant LUTs.\n",
                     folded, dropped, luts);
    }

    static std::string storage_elements(int n)
    {
        return std::to_string(n) + (n == 1 ? " storage element" : " storage elements");
    }

    void pack() override
    {
        if (ctx->args.options.count("pcf"))
            read_pcf(ctx->args.options.at("pcf").as<std::string>());
        // IO-Puffer setzt die Synthese (synth_xc2064) ein
        const pool<CellTypePort> top_ports{
                CellTypePort(id_XC2000_INBUF, id_PAD),
                CellTypePort(id_XC2000_OUTBUF, id_PAD),
                CellTypePort(id_XC2000_TOBUF, id_PAD),
                CellTypePort(id_XC2000_IOBUF, id_PAD),
        };
        h.remove_nextpnr_iobs(top_ports);
        fold_constant_tristate();
        fold_constants();
        bind_constrained_pads();
        if (clkbuf_enabled())
            bind_clock_pads();
        int moved = route_q_feedback_to_i2();
        int unused = fold_unused_lut_inputs();
        // Das FF bekommt seine Daten nur aus F bzw. FG derselben CLB. synth_xc2064 sorgt dafür, dass
        // jedes FF einen eigenen LUT hat; LUT und FF werden hier als Cluster gemeinsam platziert.
        const pool<CellTypePort> ff_d{{id_XC2000_DFF, id_D}};
        int n3 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT3, id_O}}, ff_d, Z_FF - Z_F);
        int n4 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT4, id_O}}, ff_d, Z_FF - Z_FG);
        log_info("Constrained %d LUT3/FF and %d LUT4/FF pairs, %d Q feedback inputs moved to I[2], %d unused LUT "
                 "inputs made don't-care.\n",
                 n3, n4, moved, unused);
    }

    bool clkbuf_enabled() const { return clkbuf; }

    // Ein unbelegter LUT-Eingang liest im Chip trotzdem eine Leitung (die Grundstellung seines Muxes): der
    // LUT-Inhalt darf daher nicht von ihm abhängen. INIT übernimmt für beide Werte den Teil mit Eingang = 0.
    int fold_unused_lut_inputs()
    {
        int n = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            int width = ci->type == id_XC2000_LUT3 ? 3 : ci->type == id_XC2000_LUT4 ? 4 : 0;
            if (!width)
                continue;
            uint64_t init = uint64_t(ci->params.at(id_INIT).as_int64()), next = init;
            for (int i = 0; i < width; i++) {
                if (ci->getPort(lut_in(i)))
                    continue;
                uint64_t folded = 0;
                for (int a = 0; a < (1 << width); a++)
                    if ((next >> (a & ~(1 << i))) & 1)
                        folded |= uint64_t(1) << a;
                next = folded;
                n++;
            }
            if (next != init)
                ci->params[id_INIT] = Property(int64_t(next), 1 << width);
        }
        return n;
    }

    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        if (!ctx->getBelType(bel).in(id_LUT3, id_LUT4, id_DFF))
            return true;
        Loc l = ctx->getBelLocation(bel);
        return clb_valid(l.x, l.y, explain_invalid);
    }

    // Primitive (Zelltypen mit Präfix XC2000_) -> Bel-Typ, auf dem sie sitzen
    static IdString bel_type_for(IdString cell_type)
    {
        switch (cell_type.index) {
        case id_XC2000_LUT3.index:
            return id_LUT3;
        case id_XC2000_LUT4.index:
            return id_LUT4;
        case id_XC2000_DFF.index:
            return id_DFF;
        case id_XC2000_INBUF.index:
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
        // ein IOB nur, wenn sein Pad im gewählten Gehäuse einen Pin hat
        IdString t = ctx->getBelType(bel);
        return t == bel_type_for(cell_type) && (t != id_IOB || bonded.count(bel));
    }

  private:
    HimbaechelHelpers h;
    dict<IdString, BelId> pad_bels;  // Pin des Gehäuses -> IOB-Bel
    pool<BelId> bonded;              // IOB-Bels mit Pin im Gehäuse
    std::string package = "PC68";
    std::array<BelId, 2> clock_pads; // P9 (GCLK), P43 (ACLK)
    bool clkbuf = false;             // --vopt clkbuf: Taktpuffer benutzen
    pool<IdString> clock_only_nets;  // Takte an P9/P43, die nur FF takten (preRoute)
    pool<PipId> pad_exit_pips;       // ... und die Pips von dort ins allgemeine Routing

    IdString lut_in(int i) const { return ctx->idf("I[%d]", i); }

    // --- Packing: Q-Rückführung --------------------------------------------------------------
    // Nur Eingang 3 (I[2]) eines Funktionsgenerators kann Q direkt nutzen. Hängt am LUT, der ein FF
    // speist, das Q dieses FFs an einem anderen Eingang, werden die Eingänge getauscht (INIT permutiert).
    int route_q_feedback_to_i2()
    {
        int moved = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ff = cell.second.get();
            if (ff->type != id_XC2000_DFF)
                continue;
            NetInfo *d = ff->getPort(id_D), *q = ff->getPort(id_Q);
            if (!d || !q || !d->driver.cell || !d->driver.cell->type.in(id_XC2000_LUT3, id_XC2000_LUT4))
                continue;
            CellInfo *lut = d->driver.cell;
            if (lut->getPort(lut_in(2)) == q)
                continue;
            int width = lut->type == id_XC2000_LUT4 ? 4 : 3;
            for (int i = 0; i < width; i++) {
                if (i == 2 || lut->getPort(lut_in(i)) != q)
                    continue;
                swap_lut_inputs(lut, width, i, 2);
                moved++;
                break;
            }
        }
        return moved;
    }

    void swap_lut_inputs(CellInfo *lut, int width, int a, int b)
    {
        IdString pa = lut_in(a), pb = lut_in(b);
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
        // INIT: Bit i des neuen Inhalts = Bit (i mit vertauschten Adressbits a, b) des alten
        uint64_t old_init = uint64_t(lut->params.at(id_INIT).as_int64()), new_init = 0;
        for (int i = 0; i < (1 << width); i++) {
            int j = i & ~((1 << a) | (1 << b));
            j |= (((i >> a) & 1) << b) | (((i >> b) & 1) << a);
            if ((old_init >> j) & 1)
                new_init |= uint64_t(1) << i;
        }
        lut->params[id_INIT] = Property(int64_t(new_init), 1 << width);
    }

    // --- Legalität ----------------------------------------------------------------------------
    const CellInfo *cell_at(int x, int y, int z) const
    {
        BelId bel = ctx->getBelByLocation(Loc(x, y, z));
        return bel == BelId() ? nullptr : ctx->getBoundBelCell(bel);
    }

    // Netz kommt direkt vom Eingangstreiber eines Pads (XC2000_INBUF oder O eines XC2000_IOBUF)
    static bool is_pad_input(const NetInfo *net)
    {
        const CellInfo *drv = net->driver.cell;
        return drv && drv->type.in(id_XC2000_INBUF, id_XC2000_IOBUF) && net->driver.port == id_O;
    }

    bool is_global_clock(const NetInfo *net) const
    {
        const CellInfo *drv = net->driver.cell;
        if (!clkbuf_enabled() || !is_pad_input(net))
            return false;
        if (drv->bel != BelId())
            return drv->bel == clock_pads[0] || drv->bel == clock_pads[1];
        auto fixed = drv->attrs.find(id_BEL);
        if (fixed == drv->attrs.end())
            return false;
        for (BelId pad : clock_pads)
            if (fixed->second.as_string() == ctx->getBelName(pad).str(ctx))
                return true;
        return false;
    }

    struct Req
    {
        const NetInfo *net;
        uint8_t opts;
    };

    // Jeder Anforderung eine erlaubte Quelle zuordnen; A-D führen dabei je höchstens ein Netz
    static bool assign(std::vector<Req> &reqs, size_t i, std::array<const NetInfo *, 4> &inputs)
    {
        if (i == reqs.size())
            return true;
        const Req &r = reqs.at(i);
        // Interne Quelle (Q, F, G, K; schon als passend geprüft) belegt keinen der Eingänge A-D
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
        const CellInfo *f = cell_at(x, y, Z_F), *g = cell_at(x, y, Z_G);
        const CellInfo *fg = cell_at(x, y, Z_FG), *ff = cell_at(x, y, Z_FF);

        // 1. Der F/G-Verbund (Funktion von 4 Variablen) belegt beide Funktionsgeneratoren
        if (fg && (f || g)) {
            if (explain)
                log_info("X%dY%d: LUT4 (FG) und LUT3 (F/G) gleichzeitig belegt\n", x, y);
            return false;
        }
        const NetInfo *f_out = f ? f->getPort(id_O) : fg ? fg->getPort(id_O) : nullptr;
        const NetInfo *g_out = g ? g->getPort(id_O) : fg ? fg->getPort(id_O) : nullptr;
        const NetInfo *q_out = ff ? ff->getPort(id_Q) : nullptr;

        // 2. Das FF bekommt seine Daten nur von F bzw. FG dieser CLB
        if (ff) {
            const NetInfo *d = ff->getPort(id_D);
            if (d && (!f_out || d != f_out)) {
                if (explain)
                    log_info("X%dY%d: FF-Daten kommen nicht aus F bzw. FG dieser CLB\n", x, y);
                return false;
            }
        }

        // 3. Alle Eingänge über die Multiplexer des Originals erreichbar, A-D je ein Netz
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
            // K kommt von GCLK oder von der senkrechten long.2 der Spalte, die jedes Netz erreichen kann
            // (so taktet XACT in COUNTER.BIT); zwei Takte in einer Spalte muss der Router über C lösen
            reqs.push_back({net, opts});
        };
        for (const CellInfo *c : {f, g})
            if (c)
                for (int i = 0; i < 3; i++)
                    add(c->getPort(lut_in(i)), LUT_IN_OPTS[i]);
        if (fg)
            for (int i = 0; i < 4; i++)
                add(fg->getPort(lut_in(i)), LUT_IN_OPTS[i]);
        if (ff) {
            add(ff->getPort(id_CLK), FF_CLK_OPTS);
            add(ff->getPort(id_S), FF_SET_OPTS);
            add(ff->getPort(id_R), FF_RES_OPTS);
        }
        for (const Req &r : reqs)
            if (!r.opts) {
                if (explain)
                    log_info("X%dY%d: Netz %s erreicht seinen Pin über keinen Multiplexer\n", x, y,
                             r.net->name.c_str(ctx));
                return false;
            }
        std::sort(reqs.begin(), reqs.end(),
                  [](const Req &a, const Req &b) { return __builtin_popcount(a.opts) < __builtin_popcount(b.opts); });
        std::array<const NetInfo *, 4> inputs{};
        if (!assign(reqs, 0, inputs)) {
            if (explain)
                log_info("X%dY%d: Eingangssignale passen nicht auf die Multiplexer von A-D\n", x, y);
            return false;
        }
        return true;
    }

    // router2 sucht jedes Netz nur in seiner Bounding Box plus Rand (Standard 3 Kacheln). Mit 4 Spuren je
    // Kanal reicht das nicht immer: dann wechseln sich zwei Netze an einem Draht ab und router2 kommt nicht
    // zum Ende. Auf dem 10x10-Raster darf jedes Netz daher den ganzen Chip nutzen (eigene Vorgabe über
    // die Einstellungen router2/bbMargin/x und /y bleibt möglich).
    void preRoute() override
    {
        int margin = std::max(ctx->getGridDimX(), ctx->getGridDimY());
        for (const char *k : {"router2/bbMargin/x", "router2/bbMargin/y"})
            if (!ctx->settings.count(ctx->id(k)))
                ctx->settings[ctx->id(k)] = std::to_string(margin);
        // Ein Takt an P9/P43, der nur Speicherelemente taktet, läuft wie bei XACT ganz über seinen Taktpuffer
        // (GCLK bzw. ACLK, geringer Versatz). Sonst nähme der Router zu nahen CLBs den kürzeren Weg vom Pad
        // über das allgemeine Routing.
        clock_only_nets.clear();
        pad_exit_pips.clear();
        for (BelId pad : clkbuf_enabled() ? clock_pads : std::array<BelId, 2>{}) {
            if (pad == BelId())
                continue;
            const CellInfo *ci = ctx->getBoundBelCell(pad);
            const NetInfo *net = ci ? ci->getPort(id_O) : nullptr;
            if (!net || net->users.entries() == 0)
                continue;
            bool only_ff = true;
            for (auto &u : net->users)
                only_ff &= u.cell->type == id_XC2000_DFF && u.port == id_CLK;
            if (!only_ff)
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

    // Die Eingänge der Taktpuffer gibt es nur mit --vopt clkbuf: ihr Code ist unbekannt, ein Design damit
    // ließe sich nicht in einen Bitstream übersetzen
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

    // --- Konfiguration als Text (--vopt out=, für xc2064pack) --------------------------------------
    // Format: arch/xc2064/xc2064db/config.py. Die Pips des Routings tragen ihre Zeile aus dem Graphen in den
    // Zusatzdaten; CLBs und IOBs ergeben sich aus den Zellen und den Pips innerhalb der CLB. Die Richtung
    // der Repowering-Puffer leitet xc2064pack ab ("bidi auto"), der Rest steht im Grundzustand von XACT.
    void postRoute() override
    {
        if (ctx->args.options.count("out"))
            write_config(ctx->args.options.at("out").as<std::string>());
    }

    std::string tile_wire_name(int tile, int index) const
    {
        return IdString(chip_tile_info(ctx->chip_info, tile).wires[index].name).str(ctx);
    }
    // Name (in der Kachel des Pips) der Quelle, die den Draht w in seinem Netz treibt; "" ohne
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

    // Zeile "clb" einer CLB (Felder: xc2064db/blocks.py), "" wenn die CLB unbenutzt ist
    std::string clb_config(int x, int y) const
    {
        const CellInfo *f = cell_at(x, y, Z_F), *g = cell_at(x, y, Z_G), *fg = cell_at(x, y, Z_FG);
        const CellInfo *ff = cell_at(x, y, Z_FF);
        Loc loc(x, y, 0);
        std::string xs = driver_name(tile_wire(loc, GFX_WIRE_X)), ys = driver_name(tile_wire(loc, GFX_WIRE_Y));
        if (!f && !g && !fg && !ff && xs.empty() && ys.empty())
            return "";
        auto out_name = [](const std::string &s) { return s == "G_O" ? "G" : s == "Q" || s.empty() ? "Q" : "F"; };
        auto inputs = [&](int z) {
            static const char *def[3] = {"B", "C", "Q"};
            std::string r;
            for (int i = 0; i < 3; i++) {
                std::string s = pin_driver(x, y, z, lut_in(i));
                r += (i ? ":" : "") + (s.empty() ? std::string(def[i]) : s);
            }
            return r;
        };
        auto init = [](const CellInfo *c) { return c ? uint64_t(c->params.at(id_INIT).as_int64()) : uint64_t(0); };
        std::string fin = fg ? inputs(Z_FG) : inputs(Z_F), gin = fg ? fin : inputs(Z_G);
        unsigned lutf = fg ? (init(fg) >> 8) & 0xFF : init(f) & 0xFF, lutg = fg ? init(fg) & 0xFF : init(g) & 0xFF;
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
        return stringf("BASE:%s F:%s G:%s LUTF:%02X LUTG:%02X X:%s Y:%s Q:%s SET:%s RES:%s CLK:%s", fg ? "F" : "FG",
                       fin.c_str(), gin.c_str(), lutf, lutg, out_name(xs), out_name(ys), q.c_str(), set.c_str(),
                       res.c_str(), clk.c_str());
    }

    void write_config(const std::string &file)
    {
        std::ofstream out(file);
        if (!out)
            log_error("Kann '%s' nicht schreiben\n", file.c_str());
        out << "# XC2064-Konfiguration aus nextpnr-himbaechel (arch/xc2064, Format: xc2064db/config.py)\n";
        out << "device XC2064\npackage " << package << "\nbidi auto\n";
        std::vector<std::string> lines;
        for (BelId bel : ctx->getBels()) { // IOBs: Port, Eingang direkt, Modus des Ausgangstreibers
            const CellInfo *ci = ctx->getBoundBelCell(bel);
            if (!ci || ctx->getBelType(bel) != id_IOB)
                continue;
            std::string pin = ctx->getBelName(bel)[1].str(ctx);
            const NetInfo *pad = ci->getPort(id_PAD);
            const char *dir = ci->type == id_XC2000_INBUF    ? "input"
                              : ci->type == id_XC2000_IOBUF ? "inout"
                                                            : "output";
            if (pad)
                lines.push_back(stringf("port %s %s %s", pin.c_str(), pad->name.c_str(ctx), dir));
            lines.push_back("iob " + pin + " I:PAD");
            if (ci->type == id_XC2000_INBUF)
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
                if (q) // Name des Registers für den Rückweg (xc2064netlist)
                    lines.push_back(stringf("reg %c%c %s", 'A' + y - 1, 'A' + x - 1, q->name.c_str(ctx)));
            }
        std::set<std::string> routing; // Pips des Routings (beide Richtungen eines Schalters: eine Zeile)
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

    // --- GUI: Schaltplan ----------------------------------------------------------------------
    // Kachel-Koordinaten 0..1 mit y nach unten (wie Datenblatt und Die-Fotos, X0Y0 oben links). Die
    // nextpnr-GUI zeichnet mit y nach oben, darum spiegeln box()/line() an der Horizontalen.
    //
    // Routing (xc2064db.graph): oben links die Switch-Matrizen 8.1/8.2, rechts davon der Kanal oberhalb der
    // CLB, darunter der Kanal links der CLB, mit den Leitungen in der Reihenfolge und den Abständen aus
    // Shirriffs draw.js: senkrecht local.1-4, die fünfte Leitung (local.5, im Kanal auf der Spur von
    // local.6), long.1/long.2, GCLK; waagerecht local.0 (Verbindungspunkt der fünften), local.1/3/4/5 und
    // long.1. Am Rand andere Leitungen (siehe VPOS/HPOS). ACLK läuft unten waagerecht.
    // CLB (Rahmen 0.37..0.95) nach dem Blockschaltbild im Datenblatt, von links nach rechts:
    //   Eingänge A B C D als Zeilen von links (A vom Kanal oben, D vom Kanal unten), Rückführung Q
    //   kombinatorische Logik: Multiplexer der LUT-Eingänge, LUT F, LUT G, FG als Rahmen um beide mit dem
    //   F/G-Multiplexer (B wählt)
    //   Verteiler F, FG, G mit den Multiplexern für Set (oben), Daten, Takt und Reset (unten)
    //   Speicherelement: D und Takt links, S oben, R unten, Q rechts
    //   Ausgangsschienen mit den Multiplexern X und Y, beide rechts hinaus durch den Kanal rechts
    // A läuft über die Logik zum Set-Multiplexer, C, K und D darunter zu Takt und Reset, Q unten herum
    // zurück zu den LUTs. Direktverbindungen: X am rechten Rand hinauf zu C/D der CLB darüber und hinab
    // zu A/B der CLB darunter, Y weiter nach rechts zu B der Nachbar-CLB.
    // Keine Leitung läuft durch ein Bauteil. Im Routing zeichnet jedes Wire seine ganze Leitung bis zu den
    // Kreuzungen, an denen es geschaltet werden kann, der Pip nur das Kästchen dort (wie Metall und
    // Schalter im Chip). In der CLB sind Pips Abgriffe mit Punkt (Schiene -> Multiplexer-Eingang).
    // Unbenutzte Pips sind gedämpft, ein benutzter Pip zeigt zusätzlich seinen Weg durch den Multiplexer.
    static constexpr int LAST = 9; // 9. Switch-Matrix-Spalte/-Zeile

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
    // Linienzug in Kachel-Koordinaten
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
    // Pip als Kästchen am Kreuzungspunkt
    void pip_box(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float x, float y) const
    {
        box(g, style, loc.x + x - 0.006, loc.y + y - 0.006, loc.x + x + 0.006, loc.y + y + 0.006);
    }

    // --- Lage der Kanalleitungen ---
    // Nach Shirriffs draw.js (Reihenfolge und Abstände der Bildschirmkoordinaten), getrennt nach Spalte A
    // (Rand links), B-H und I (Rand rechts) bzw. Zeile A (oben), B-H und I (unten). Senkrechte Leitungen
    // liegen im Kanal links der CLB (x 0..0.36), waagerechte im Kanal oberhalb (y 0..0.36); -1: gibt es dort
    // nicht.
    enum VLine
    {
        V_LOC1, V_LOC2, V_LOC3, V_LOC4, V_LOC5, V_LOC6, V_LONG1, V_LONG2, V_LONG3, V_LONG4, V_CLK, V_X, V_N
    };
    enum HLine
    {
        H_LOC0, H_LOC1, H_LOC2, H_LOC3, H_LOC4, H_LOC5, H_LONG1, H_LONG2, H_LONG3, H_CLK, H_N
    };
    static constexpr float VPOS[3][V_N] = {
            // Spalte A: long.2 22, local.1-4 26-38, long.3 44, long.4 48, clk 52, x 74
            {0.054, 0.078, 0.102, 0.126, -1, -1, -1, 0.030, 0.162, 0.186, 0.210, 0.342},
            // B-H: local.1-4 108-120, local.5 126, local.6 130, long.1 134, long.2 138, clk 142, x 146
            {0.040, 0.071, 0.102, 0.134, 0.181, 0.212, 0.243, 0.274, -1, -1, 0.305, 0.336},
            // Spalte I: long.1 626, long.2 630, local.1-4 636-648, long.3 652
            {0.118, 0.149, 0.181, 0.212, -1, -1, 0.040, 0.071, 0.243, -1, -1, -1},
    };
    static constexpr float HPOS[3][H_N] = {
            // Zeile A: CLK.AA.O 22, long.2 26, local.1-4 30-42, long.3 48
            {-1, 0.114, 0.156, 0.198, 0.240, -1, -1, 0.072, 0.303, 0.030},
            // B-H: local.0 112, local.1 114, local.3 118, local.4 122, local.5 126, long.1 132
            {0.030, 0.055, -1, 0.105, 0.155, 0.205, 0.280, -1, -1, -1},
            // Zeile I: long.1 624, local.1-4 630-642, long.2 646, clk 652
            {-1, 0.103, 0.145, 0.187, 0.229, -1, 0.040, 0.271, -1, 0.334},
    };
    static int col_kind(int x) { return x <= 1 ? 0 : x >= LAST ? 2 : 1; }
    static int row_kind(int y) { return y <= 1 ? 0 : y >= LAST ? 2 : 1; }
    static float vx(int x, int l) { return VPOS[col_kind(x)][l]; }
    static float hy(int y, int l) { return HPOS[row_kind(y)][l]; }

    // Switch-Matrizen 8.1 (m = 0) und 8.2 (m = 1): senkrecht local.1/2 bzw. local.3/4, waagerecht je nach
    // Zeile (G-Lage der Pins, xc2064db.switches); an den vier Ecken des Chips keine
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

    // Kanaldraht aus der Grafik-ID: senkrecht oder waagerecht, Leitung, Nachbarstück (dx, dy)
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
    // Lage an einer Kreuzung: x der senkrechten (hline: die gekreuzte waagerechte, -1 in der CLB), y der
    // waagerechten Leitung. Das eigene Stück der fünften Leitung kreuzt local.3/4 auf der Spur von local.6.
    static float chan_x(Loc loc, const Chan &c, int hline)
    {
        if (c.line == V_LOC5 && c.dx == 0 && c.dy == 0 && loc.y > 1 && (hline == H_LOC3 || hline == H_LOC4))
            return vx(loc.x, V_LOC6);
        return c.dx + vx(loc.x + c.dx, c.line);
    }
    static float chan_y(Loc loc, const Chan &c) { return c.dy + hy(loc.y + c.dy, c.line); }
    // Leitung, die in dieser Kachel an einer Switch-Matrix endet (local.1-4 senkrecht, die Zeilen der Matrizen)
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
    // Pin einer Switch-Matrix: Stück oben/unten bzw. links/rechts am Rand der Matrix
    static std::pair<float, float> sm_pin_pt(Loc loc, const Chan &c)
    {
        if (c.vert) {
            Box b = sm_box(loc.x, loc.y, sm_of_v(c.line));
            return {vx(loc.x, c.line), c.dy < 0 ? b.y0 : b.y1};
        }
        Box b = sm_box(loc.x, loc.y, sm_of_h(loc.y, c.line));
        return {c.dx < 0 ? b.x0 : b.x1, hy(loc.y, c.line)};
    }

    // --- CLB-Geometrie ---
    // Spalten (x): Pins A/D, Schienen der Eingänge, Multiplexer der LUTs, LUTs, Verteiler F/FG/G,
    // Multiplexer des Speicherelements, Speicherelement, Ausgangsschienen, Ausgangsmultiplexer
    static constexpr float CLB_X0 = 0.384, CLB_X1 = 0.955; // Rahmen
    static constexpr float D_PIN_X = 0.358, A_PIN_X = 0.371; // D von unten, A von oben
    static constexpr float QL_X = 0.396, D_X = 0.407, C_X = 0.418, B_X = 0.429, A_X = 0.44, K_END_X = 0.448;
    static constexpr float MUX_X = 0.454, FMUX_X = 0.678, OMUX_X = 0.886, MUX_W = 0.03, MUX_STEP = 0.013,
                           MUX_SLANT = 0.005;
    static constexpr float FGF_X0 = 0.492, BOX_X0 = 0.502, BOX_X1 = 0.57, TAP_X = 0.582;
    static constexpr float M_X0 = 0.594, M_X1 = 0.616, FGF_X1 = 0.628;
    static constexpr float FF_X0 = 0.726, FF_X1 = 0.814, FF_PIN_X = 0.77;
    static constexpr float X_DN_X = 0.93, X_UP_X = 0.942; // Direktverbindungen von X nach unten/oben
    // ... und ihre Abzweige in der Nachbarkachel: zu A und B der CLB darunter, zu D und C der CLB darüber
    static constexpr float XT_A_Y = 0.31, XT_B_Y = 0.335, XB_D_Y = 0.975, XB_C_Y = 0.965;
    // Direktleitungen im Kanal: X von oben/unten bzw. Pad auf der Spur von col.x, Y von links auf local.6
    static constexpr float DIR_X = 0.336, YL_X = 0.212;
    // Zeilen (y)
    static constexpr float A_ROW = 0.392, B_ROW = 0.476, C_ROW = 0.523; // Eingänge von links
    static constexpr float C_LINE = 0.792, K_LINE = 0.805, D_ROW = 0.866; // unter der Logik zum FF
    static constexpr float F_TOP = 0.45, G_TOP = 0.61, LUT_H = 0.146;
    static constexpr float FGF_Y0 = 0.442, FGF_Y1 = 0.764; // FG-Rahmen
    static constexpr float M_Y0 = 0.56, M_Y1 = 0.646, M_IN_F = 0.577, M_IN_G = 0.629; // F/G-Multiplexer
    static constexpr float M_SEL_X = (M_X0 + M_X1) / 2, SEL_Y = 0.774;
    static constexpr float FF_Y0 = 0.54, FF_Y1 = 0.826;
    static constexpr float F_ROW = 0.45, FG_ROW = 0.463, G_ROW = 0.476; // F, FG, G über dem FF nach rechts
    static constexpr float Q_RAIL = 0.905;                              // Q unter allem zurück nach links
    static constexpr float X_MUX_Y = 0.379, Y_MUX_Y = 0.4675;
    static constexpr float X_Y = X_MUX_Y + 2.5 * MUX_STEP, Y_Y = Y_MUX_Y + 2.5 * MUX_STEP; // Ausgänge X, Y

    enum Col
    {
        COL_LUT, // Eingänge der LUTs
        COL_FF,  // Eingänge des Speicherelements
        COL_OUT, // Ausgänge X, Y
    };
    // Schiene bzw. Verteiler, an dem eine Quelle für eine Multiplexer-Spalte abgegriffen wird
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

    // Multiplexer: getriebene Leitung, Spalte, Lage, Eingänge von oben nach unten
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
    // Multiplexer, die eine Leitung treibt. FG belegt F und G, seine Eingänge liegen an beiden an.
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
    // oberster und unterster Abgriff einer Quelle: in den Spalten LUT/FF bzw. an den Ausgängen
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
    // Verbindungspunkt auf einer Schiene
    void dot(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, float x, float y) const
    {
        const float r = 0.0025;
        box(g, style, loc.x + x - r, loc.y + y - r, loc.x + x + r, loc.y + y + r);
        poly(g, style, loc, {{x - r, y - r}, {x + r, y + r}});
        poly(g, style, loc, {{x - r, y + r}, {x + r, y - r}});
    }

    // Ausgang von F, G, FG bzw. des Speicherelements
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

    // Seite einer IO-Kachel: 'T'op, 'B'ottom, 'L'eft, 'R'ight
    static char io_side(Loc loc)
    {
        if (loc.y == 0)
            return 'T';
        if (loc.y == LAST)
            return 'B';
        return loc.x == 0 ? 'L' : 'R';
    }

    // Repowering-Puffer an den Grenzen der 9 Sektionen (Datenblatt, xc2064db.graph): auf den Einzelsegmenten,
    // die über die Zeilen D und G bzw. die Spalten D und G hinweg laufen, kurz vor deren Kanal (bei Shirriff
    // zwischen io3 und local.0 bzw. clbw3 und local.1). Zwei Dreiecke Spitze an Spitze: er treibt in eine der
    // beiden Richtungen, welche, ergibt sich aus dem Routing.
    static constexpr float BUF_D = 0.011, BUF_W = 0.005, BUF_L = 0.007;
    static bool buffered_segment(int k) { return k == 3 || k == 6; } // Stücke @C und @F
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

    // Eigenes Stück einer Kanalleitung zeichnen (die ganze Leitung bis zu den Pips, Nachbarstücke nichts)
    void draw_channel(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, const Chan &c) const
    {
        const int x = loc.x, y = loc.y;
        if (c.vert) {
            float px = vx(x, c.line);
            if (px < 0)
                return;
            if (c.line <= V_LOC5 && buffered_segment(y))
                bidi_buffer(g, style, loc, true, 1 + BUF_D, px);
            if (c.line <= V_LOC4) { // Einzelsegment: von Matrix zu Matrix (am Rand bis in den Randkanal)
                float y0 = tile_has_sm(x, y) ? sm_box(x, y, sm_of_v(c.line)).y1 : 0.0f;
                float y1 = tile_has_sm(x, y + 1) ? 1 + sm_box(x, y + 1, sm_of_v(c.line)).y0 : 1.36f;
                poly(g, style, loc, {{px, y0}, {px, y1}});
            } else if (c.line == V_LOC5) { // fünfte Leitung: Verbindungspunkt, Spur local.6, Knick, local.5
                float end = 1 + (y + 1 >= LAST ? hy(LAST, H_LOC3) : hy(y + 1, H_LOC4)) + 0.015f;
                if (y == 1) {
                    poly(g, style, loc, {{px, hy(1, H_LOC1)}, {px, end}});
                } else {
                    float j = hy(y, H_LOC0), p6 = vx(x, V_LOC6), jog = hy(y, H_LOC5) + 0.03f;
                    poly(g, style, loc, {{px, j}, {p6, j}, {p6, jog}, {px, jog}, {px, end}});
                }
            } else { // Long Line, GCLK: über die ganze Höhe, am Rand bis in den Randkanal
                float y0 = y == 1 ? hy(1, H_CLK) : 0.0f, y1 = y == LAST ? hy(LAST, H_CLK) + 0.02f : 1.0f;
                poly(g, style, loc, {{px, y0}, {px, y1}});
                if (c.line == V_CLK && y == 1) // CLK.AA.O: vom Taktpuffer oben links zu allen Spalten
                    poly(g, style, loc, {{x == 1 ? px : 0.0f, hy(1, H_CLK)}, {1.0f, hy(1, H_CLK)}});
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
                float x0 = x == 1 ? vx(1, V_LONG2) : 0.0f, x1 = x == LAST ? vx(LAST, V_LONG3) + 0.02f : 1.0f;
                poly(g, style, loc, {{x0, py}, {x1, py}});
            }
        }
    }

    // --- IOB-Geometrie ---
    // Ein IOB liegt außen neben dem Kanal parallel zum Rand: oben/unten neben dem waagerechten Kanal der
    // ersten bzw. letzten Zeile, links/rechts neben dem senkrechten der ersten bzw. letzten Spalte. Neben
    // jeder Rand-CLB liegen bis zu zwei IOBs: das erste Pad ihrer Pad-Kachel (z = 0) in der ersten Hälfte,
    // das zweite Pad der folgenden Kachel (z = 1) in der zweiten.
    // Koordinaten: r entlang des Rands ab dem Anfang des IOB, d vom Chiprand nach innen. Aufbau wie im
    // Datenblatt, von außen nach innen: Pad; Ausgangstreiber (Dreieck zum Pad) und Eingangstreiber
    // (Dreieck nach innen); Multiplexer für den Ausgang (Bel-Pin I, im Datenblatt "O") und das Tristate
    // T; dann laufen die Leitungen von Ausgang, T und Eingang (Bel-Pin O, im Datenblatt "I") quer über den
    // Kanal parallel zum Rand. Wie bei Shirriff (iob.js: Pin-Leitungen io1-io6, x, clbl, clbr) knickt ein
    // Pin dahinter in eine Stichleitung parallel zum Rand ab, die die Leitungen quer zum Rand kreuzt.
    // Welche Leitungen ein Pin schalten kann, folgt aus den Pips des Chips (xc2064db.graph); die Zeichnung
    // sucht sie dort und setzt an jede Kreuzung ein Kästchen wie im Kanal.
    // Direktverbindungen: X (rechts auch Y) der Rand-CLB läuft in den Ausgangsmultiplexer (oben/unten ist
    // das zweite IOB dafür gespiegelt, rechts knickt der Weg zum zweiten IOB vor dem Randkanal ab); der
    // Eingang vom Pad läuft oben, unten und links auf seiner Stichleitung weiter zu A/B, D/C bzw. B der
    // Rand-CLB (oben/unten mit Abzweig auf der Spur von col.x).
    static constexpr float IOB_U0 = 0.385, IOB_DU = 0.3135, IOB_W = 0.27; // Lage am Kanalstück, Breite
    static constexpr float IOB_D0 = 0.18, IOB_D1 = 0.58;                 // Rahmen
    static constexpr float PAD_R = 0.135, PAD_HW = 0.04, PAD_D0 = 0.03, PAD_D1 = 0.11, JCT_D = 0.22;
    static constexpr float OB_R = 0.07, OB_TIP = 0.28, OB_BASE = 0.36;  // Ausgangstreiber
    static constexpr float IB_R = 0.235, IB_BASE = 0.26, IB_TIP = 0.34; // Eingangstreiber
    static constexpr float OM_R0 = 0.012, OM_R1 = 0.13, TM_R0 = 0.15, TM_R1 = 0.20; // Multiplexer
    static constexpr float MX_D0 = 0.44, OM_D1 = 0.52, TM_D1 = 0.50, EN_D = 0.32;
    static constexpr float O_R = 0.07, T_R = 0.175, I_R = IB_R; // Leitungen über den Kanal
    static constexpr float PIN_R[3] = {O_R, I_R, T_R};          // Bel-Pins I, O, T (Reihenfolge der Grafik-IDs)
    static constexpr float DX_R = 0.0265, DY_R = 0.115;         // X, Y direkt (rechter Rand, z = 0)
    static constexpr float DX1_R = 0.025, DY1_R = 0.045;        // ... z = 1, vor dem Ausgang
    static constexpr float JOG_X = 0.98, JOG_Y = 0.97;          // Knick dorthin, vor dem Randkanal
    // Stichleitungen: links auf Shirriffs Spuren col.A.local.5, io1, io2, io3, sonst in Schritten hinter
    // dem Kanal (oben/unten/rechts ist dort weniger Platz als bei Shirriff)
    static constexpr float STUB_STEP = 0.011;
    static constexpr float L_STUB[4] = {0.234, 0.270, 0.294, 0.318};

    struct Iob
    {
        char side;
        float u0;    // Anfang entlang des Rands, in der eigenen Kachel
        float off;   // oben/links liegt der Kanal in der Nachbarkachel: IOB näher an ihn heran
        bool mirror; // oben/unten das zweite IOB: Ausgangsmultiplexer zur Direktleitung von X hin
    };
    static Iob iob(Loc loc, int z)
    {
        char s = io_side(loc);
        return Iob{s, z ? IOB_U0 + IOB_DU - 1 : IOB_U0, (s == 'T' || s == 'L') ? 0.30f : 0.0f,
                   (s == 'T' || s == 'B') && z == 1};
    }
    // Punkt (u entlang des Rands, d vom Chiprand) in Kachel-Koordinaten der Pad-Kachel
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
    // u zu r im IOB und umgekehrt
    static float pin_u(const Iob &b, float r) { return b.mirror ? b.u0 + IOB_W - r : b.u0 + r; }
    static float iob_r(const Iob &b, float u) { return b.mirror ? IOB_W - (u - b.u0) : u - b.u0; }
    // Punkt im IOB (d ohne Versatz) in Kachel-Koordinaten
    static std::pair<float, float> iob_pt(const Iob &b, float r, float d)
    {
        return edge_pt(b.side, pin_u(b, r), d + b.off);
    }
    // Tiefe der Stichleitung von Ausgang (input = false) bzw. Eingang eines IOB. Die Pins eines IOB
    // kreuzen sich nicht: der Pin weiter weg von den Leitungen quer zum Rand liegt tiefer.
    static float stub_d(char side, int z, bool input)
    {
        static constexpr int RANK[4][2][2] = {
                {{2, 3}, {0, 1}}, // oben: z = 0 (Leitungen links davon), z = 1 (rechts davon)
                {{2, 3}, {0, 1}}, // unten
                {{0, 1}, {2, 3}}, // links: z = 0 (Leitungen darüber), z = 1 (darunter)
                {{0, 1}, {3, 2}}, // rechts
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
    // r, an dem X bzw. Y einer Rand-CLB direkt in den Ausgangsmultiplexer läuft
    static float direct_r(const Iob &b, int z, bool y)
    {
        if (b.side == 'R')
            return z ? (y ? DY1_R : DX1_R) : (y ? DY_R : DX_R);
        return iob_r(b, (b.side == 'T' ? X_UP_X : X_DN_X) - 1); // X der Rand-CLB links daneben
    }

    struct IobPip
    {
        float u, d;
        bool cross; // Kreuzung mit der Stichleitung (Leitung quer zum Rand)
    };
    // Lage des Pips zwischen Pin p (0: I, 1: O, 2: T) des IOB z und der Leitung other (Grafik-ID in der
    // Pad-Kachel). false: kein Kästchen (X/Y direkt).
    static bool iob_pip(Loc loc, int z, int p, int32_t other, IobPip &res)
    {
        Iob b = iob(loc, z);
        float u = pin_u(b, PIN_R[p]);
        if (other == GFX_WIRE_GCLK) { // P9: CLK.AA.O über der Zeile A (Ausgangs-Mux und Taktpuffer)
            res = {u, 1 + hy(1, H_CLK), false};
            return true;
        }
        if (other == GFX_WIRE_ACLK) { // P43: row.I.clk
            res = {u, 1 - hy(LAST, H_CLK), false};
            return true;
        }
        Chan c = chan(other);
        if (!c.ok)
            return false;
        float pos = c.vert ? chan_x(loc, c, -1) : chan_y(loc, c);
        if (c.vert == (b.side == 'L' || b.side == 'R')) // parallel zum Rand: kreuzt den Pin selbst
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
    // Multiplexer: Eingänge auf der Seite zum Kanal (d1), Ausgang zum Pad (d0)
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

    // --- Drähte und Knoten aus der Chip-Datenbank (für die Zeichnung der IOBs) ---
    int32_t wire_gfx(WireId w) const { return chip_tile_info(ctx->chip_info, w.tile).wires[w.index].tile_wire; }
    // Knoten des Drahts mit der Grafik-ID gfx in der Kachel loc, WireId() wenn es ihn dort nicht gibt
    WireId tile_wire(Loc loc, int32_t gfx) const
    {
        int tile = tile_by_xy(ctx->chip_info, loc.x, loc.y);
        const auto &wires = chip_tile_info(ctx->chip_info, tile).wires;
        for (int i = 0; i < wires.ssize(); i++)
            if (wires[i].tile_wire == gfx)
                return ctx->normalise_wire(tile, i);
        return WireId();
    }
    // alle Drähte eines Knotens: fn(Kachel, Grafik-ID)
    template <typename Fn> void node_wires(WireId node, Fn fn) const
    {
        for (WireId tw : ctx->get_tile_wire_range(node)) {
            Loc l;
            tile_xy(ctx->chip_info, tw.tile, l.x, l.y);
            fn(l, wire_gfx(tw));
        }
    }
    // Gehört zum Knoten des Drahts gfx in loc auch der Draht target in der Kachel (tx, ty)?
    bool reaches(Loc loc, int32_t gfx, int tx, int ty, int32_t target) const
    {
        WireId w = tile_wire(loc, gfx);
        bool found = false;
        if (w != WireId())
            node_wires(w, [&](Loc l, int32_t id) { found |= l.x == tx && l.y == ty && id == target; });
        return found;
    }
    // Lage der Stichleitung des Pads, dessen Eingang über PT, PB bzw. PL direkt in die Kachel clb führt, in
    // deren Kachel-Koordinaten (oben/unten y, links x)
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

    // Leitung eines IOB-Pins: vom Multiplexer bzw. Eingangstreiber über den Kanal parallel zum Rand bis zu
    // seiner letzten Kreuzung oder zur Stichleitung, die die Leitungen quer zum Rand und beim Eingang die
    // Direkteingänge der Rand-CLB erreicht
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
            // direkt in die Rand-CLB: oben zu A (Kästchen auf der Stichleitung) und B, unten zu D und C
            // (Abzweig auf der Spur von col.x), links zu B
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
        if (p == 0) { // Ausgang zum Pad: Multiplexer -> Ausgangstreiber
            iob_mux(g, style, loc, b, OM_R0, OM_R1, MX_D0, OM_D1);
            iob_line(g, style, loc, b, {{O_R, de}, {O_R, OM_D1}});
            iob_line(g, style, loc, b, {{O_R, MX_D0}, {O_R, OB_BASE}});
        } else if (p == 2) { // Tristate: Multiplexer -> Freigabe des Ausgangstreibers
            iob_mux(g, style, loc, b, TM_R0, TM_R1, MX_D0, TM_D1);
            iob_line(g, style, loc, b, {{T_R, de}, {T_R, TM_D1}});
            iob_line(g, style, loc, b, {{T_R, MX_D0}, {T_R, EN_D}, {OB_R + 0.015, EN_D}});
        } else { // Eingang vom Pad: Eingangstreiber -> über den Kanal
            iob_line(g, style, loc, b, {{I_R, IB_TIP}, {I_R, de}});
        }
        if (!stub)
            return;
        poly(g, style, loc, {edge_pt(b.side, lo, ds), edge_pt(b.side, hi, ds)});
        auto tee = [&](float t) { // Abzweig mitten auf der Stichleitung
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

    // X bzw. Y nach rechts durch den Kanal; in Spalte H durch den Randkanal bis in die IOBs, die es direkt
    // nehmen: z = 0 daneben gerade, z = 1 der Kachel darunter über einen Knick vor dem Randkanal
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
        case id_LUT3.index: { // F oben, G darunter
            float top = loc.z == Z_F ? F_TOP : G_TOP;
            box(g, style, x + BOX_X0, y + top, x + BOX_X1, y + top + LUT_H);
            break;
        }
        case id_LUT4.index: { // FG: F und G mit dem F/G-Multiplexer (B wählt) in einem Rahmen
            float fy = source_point(GFX_WIRE_F_O).second, gy = source_point(GFX_WIRE_G_O).second;
            box(g, style, x + BOX_X0, y + F_TOP, x + BOX_X1, y + F_TOP + LUT_H);
            box(g, style, x + BOX_X0, y + G_TOP, x + BOX_X1, y + G_TOP + LUT_H);
            poly(g, style, loc,
                 {{FGF_X0, FGF_Y0}, {FGF_X1, FGF_Y0}, {FGF_X1, FGF_Y1}, {FGF_X0, FGF_Y1}, {FGF_X0, FGF_Y0}});
            draw_mux(g, style, loc, M_X0, M_Y0, M_X1, M_Y1);
            poly(g, style, loc, {{BOX_X1, fy}, {TAP_X, fy}, {TAP_X, M_IN_F}, {M_X0, M_IN_F}});
            poly(g, style, loc, {{BOX_X1, gy}, {TAP_X, gy}, {TAP_X, M_IN_G}, {M_X0, M_IN_G}});
            dot(g, style, loc, TAP_X, fy);
            dot(g, style, loc, TAP_X, gy);
            break;
        }
        case id_DFF.index: { // D und Takt (mit Dreieck) links, S oben, R unten, Q rechts
            float cy = mux_out_y(MUXES[MUX_FF_CLK]);
            box(g, style, x + FF_X0, y + FF_Y0, x + FF_X1, y + FF_Y1);
            poly(g, style, loc, {{FF_X0, cy - 0.008}, {FF_X0 + 0.012, cy}, {FF_X0, cy + 0.008}});
            break;
        }
        case id_IOB.index: { // Rahmen, Pad, Ausgangstreiber (zum Pad) und Eingangstreiber (nach innen)
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
            break;
        }
        }
    }

    void drawWire(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, IdString wire_type,
                  int32_t tilewire, IdString tile_type) override
    {

        // CLB: Multiplexer mit Ausgang zum Bel bzw. zum Pin
        bool is_mux = for_muxes(tilewire, [&](const Mux &m) {
            float ox = mux_x(m) + MUX_W, oy = mux_out_y(m);
            draw_mux(g, style, loc, mux_x(m), m.y_top, ox, mux_bot(m));
            switch (m.out) {
            case GFX_WIRE_X: // durch den Kanal rechts bis long.1 (Spalte H: in die IOBs rechts), Direktleitungen
                out_right(g, style, loc, ox, oy, false);
                if (loc.y > 1) { // zu D und C der CLB darüber
                    poly(g, style, loc,
                         {{X_UP_X, oy}, {X_UP_X, XB_C_Y - 1}, {DIR_X, XB_C_Y - 1}, {DIR_X, C_ROW - 1}});
                    poly(g, style, loc, {{X_UP_X, XB_D_Y - 1}, {D_PIN_X, XB_D_Y - 1}});
                    dot(g, style, loc, X_UP_X, oy);
                    dot(g, style, loc, X_UP_X, XB_D_Y - 1);
                } else if (reaches(loc, GFX_WIRE_X, loc.x + 1, 0, GFX_WIRE_IO1_X)) { // ins IOB darüber
                    poly(g, style, loc, {{X_UP_X, oy}, {X_UP_X, -1 + 0.30f + OM_D1}});
                    dot(g, style, loc, X_UP_X, oy);
                }
                if (loc.y < ctx->getGridDimY() - 2) { // zu A und B der CLB darunter
                    poly(g, style, loc,
                         {{X_DN_X, oy}, {X_DN_X, 1 + XT_B_Y}, {DIR_X, 1 + XT_B_Y}, {DIR_X, 1 + B_ROW}});
                    poly(g, style, loc, {{X_DN_X, 1 + XT_A_Y}, {A_PIN_X, 1 + XT_A_Y}});
                    dot(g, style, loc, X_DN_X, oy);
                    dot(g, style, loc, X_DN_X, 1 + XT_A_Y);
                } else if (reaches(loc, GFX_WIRE_X, loc.x + 1, LAST, GFX_WIRE_IO1_X)) { // ins IOB darunter
                    poly(g, style, loc, {{X_DN_X, oy}, {X_DN_X, 2 - OM_D1}});
                    dot(g, style, loc, X_DN_X, oy);
                }
                break;
            case GFX_WIRE_Y: // durch den Kanal rechts bis long.2, Abzweig auf local.6 zu B der Nachbar-CLB
                out_right(g, style, loc, ox, oy, true);
                if (loc.x < LAST - 1) {
                    poly(g, style, loc, {{1 + YL_X, oy}, {1 + YL_X, B_ROW}});
                    dot(g, style, loc, 1 + YL_X, oy);
                }
                break;
            case GFX_WIRE_FF_S: // Set von oben
                poly(g, style, loc, {{ox, oy}, {FF_PIN_X, oy}, {FF_PIN_X, FF_Y0}});
                break;
            case GFX_WIRE_FF_R: // Reset von unten
                poly(g, style, loc, {{ox, oy}, {FF_PIN_X, oy}, {FF_PIN_X, FF_Y1}});
                break;
            default:
                poly(g, style, loc, {{ox, oy}, {m.col == COL_LUT ? BOX_X0 : FF_X0, oy}});
                break;
            }
        });
        if (is_mux)
            return;
        // Abzweig mit Punkt, wenn die Leitung über y hinaus weiterläuft
        auto tee = [&](float tx, float ty, float lo, float hi) {
            if (ty > lo && ty < hi)
                dot(g, style, loc, tx, ty);
        };
        float top, bot;
        switch (tilewire) {
        case GFX_WIRE_A: // Pin oben, Zeile von links
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{A_PIN_X, 0.03}, {A_PIN_X, A_ROW}, {A_X, A_ROW}, {A_X, bot}});
            return;
        case GFX_WIRE_B: // Pins links
            poly(g, style, loc, {{0.03, B_ROW}, {B_X, B_ROW}, {B_X, SEL_Y}});
            return;
        case GFX_WIRE_C:
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{0.03, C_ROW}, {C_X, C_ROW}, {C_X, bot}});
            return;
        case GFX_WIRE_D: // Pin unten (kreuzt Kanal und Long Line darunter), Zeile von links
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {{D_PIN_X, 1.28}, {D_PIN_X, D_ROW}, {D_X, D_ROW}, {D_X, top}});
            return;
        case GFX_WIRE_K: // von long.2 (Spalte A: long.4, ACLK) und GCLK
            poly(g, style, loc, {{(loc.x == 1 ? vx(1, V_LONG4) : vx(loc.x, V_LONG2)) - 0.005f, K_LINE}, {K_END_X, K_LINE}});
            return;
        case GFX_WIRE_F_O:
        case GFX_WIRE_G_O:
        case GFX_WIRE_FG_O: { // Ausgang -> Verteiler, über dem Speicherelement -> Ausgangsschiene
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
        case GFX_WIRE_Q: { // Ausgang -> Schiene rechts (X, Y), unten herum zurück zu den LUTs
            auto src = source_point(tilewire);
            float rx = src_x(COL_OUT, tilewire), rtop, rbot;
            taps(tilewire, true, rtop, rbot);
            taps(tilewire, false, top, bot);
            poly(g, style, loc, {src, {rx, src.second}});
            poly(g, style, loc, {{rx, rtop}, {rx, Q_RAIL}, {QL_X, Q_RAIL}, {QL_X, top}});
            tee(rx, src.second, rtop, Q_RAIL);
            return;
        }
        case GFX_WIRE_FG_I3: // B wählt im F/G-Multiplexer
            poly(g, style, loc, {{M_SEL_X, SEL_Y}, {M_SEL_X, M_Y1 - MUX_SLANT / 2}});
            return;
        case GFX_WIRE_XT: // Teile von Knoten, die eine Nachbarkachel zeichnet
        case GFX_WIRE_XB:
        case GFX_WIRE_YL:
        case GFX_WIRE_PL:
        case GFX_WIRE_PT:
        case GFX_WIRE_PB:
            return;
        }

        // IOB: Multiplexer und Leitungen der Pins (Taktpuffer: P9 bzw. P43 kreuzt seine Taktleitung, das
        // Kästchen dort zeichnet der Pip)
        if (tilewire >= GFX_WIRE_IO0_I && tilewire <= GFX_WIRE_IO1_T) {
            int z = (tilewire - GFX_WIRE_IO0_I) / 3, p = (tilewire - GFX_WIRE_IO0_I) % 3; // I, O, T
            draw_iob_pin(g, style, loc, z, p);
            return;
        }

        // Kanäle: das eigene Stück zeichnet die ganze Leitung, Nachbarstücke (_U, _R, _L, _D, ...) nichts.
        // In den Pad-Kacheln links und oben liegen nur Zugänge zu Leitungen der Nachbarkacheln.
        Chan c = chan(tilewire);
        if (c.ok && c.dx == 0 && c.dy == 0 && loc.x > 0 && loc.y > 0)
            draw_channel(g, style, loc, c);
        // Sonst Teile von Knoten, die andere Drähte zeichnen (X/Y direkt im IOB)
    }

    // Grafik-ID des Drahts, den ein Knoten in der Kachel loc hat. nextpnr übergibt drawPip die
    // Grafik-ID des kanonischen Knoten-Drahts, der in einer anderen Kachel liegen kann.
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
        // nextpnr blendet unbenutzte Pips aus. Hier gehören sie zum Schaltplan und werden gedämpft gezeichnet.
        if (style == GraphicElement::STYLE_HIDDEN)
            style = GraphicElement::STYLE_INACTIVE;
        src_id = local_gfx_id(src, loc, src_id);
        dst_id = local_gfx_id(dst, loc, dst_id);

        // Kanäle: Switch-Matrix (Pin zu Pin), Kreuzung (Kästchen), Verbindungspunkt der fünften Leitung
        Chan cs = chan(src_id), cd = chan(dst_id);
        if (cs.ok && cd.ok) {
            if (sm_line(loc, cs) && sm_line(loc, cd)) {
                auto a = sm_pin_pt(loc, cs), b = sm_pin_pt(loc, cd);
                poly(g, style, loc, {a, b});
            } else if (cs.vert && cd.vert) { // nur die fünfte Leitung: Stück darüber -> eigenes Stück
                pip_box(g, style, loc, vx(loc.x, V_LOC5), hy(loc.y, H_LOC0));
            } else {
                const Chan &v = cs.vert ? cs : cd, &h = cs.vert ? cd : cs;
                pip_box(g, style, loc, chan_x(loc, v, h.line), chan_y(loc, h));
            }
            return;
        }

        // CLB-intern: Abgriff an Schiene bzw. Verteiler -> Multiplexer-Eingang, benutzt auch weiter zum Ausgang
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
        if (dst_id == GFX_WIRE_FG_I3) { // B -> Auswahl des F/G-Multiplexers
            poly(g, style, loc, {{B_X, SEL_Y}, {M_SEL_X, SEL_Y}});
            return;
        }

        // Routing -> CLB-Eingänge (Mux-Quellen aus clb.js)
        switch (dst_id) {
        case GFX_WIRE_A: // Pin kreuzt den Kanal oberhalb
            if (cs.ok)
                pip_box(g, style, loc, A_PIN_X, chan_y(loc, cs));
            else if (src_id == GFX_WIRE_XT) // X der CLB darüber
                pip_box(g, style, loc, A_PIN_X, XT_A_Y);
            else if (src_id == GFX_WIRE_PT) // Pad oben: auf seiner Stichleitung
                pip_box(g, style, loc, A_PIN_X, pad_stub(src, loc));
            return;
        case GFX_WIRE_B:
        case GFX_WIRE_C: { // Zeilen kreuzen den Kanal links
            float py = dst_id == GFX_WIRE_B ? B_ROW : C_ROW;
            if (cs.ok)
                pip_box(g, style, loc, chan_x(loc, cs, -1), py);
            else if (src_id == GFX_WIRE_XT || src_id == GFX_WIRE_XB || src_id == GFX_WIRE_PT ||
                     src_id == GFX_WIRE_PB) // Direktverbindung von X bzw. Pad darüber/darunter (col.x)
                pip_box(g, style, loc, DIR_X, py);
            else if (src_id == GFX_WIRE_PL) // Direktverbindung vom Pad links: auf seiner Stichleitung
                pip_box(g, style, loc, pad_stub(src, loc), py);
            else if (src_id == GFX_WIRE_YL) // Direktverbindung von Y der CLB links (local.6)
                pip_box(g, style, loc, YL_X, py);
            return;
        }
        case GFX_WIRE_D: // Pin kreuzt den Kanal unterhalb
            if (cs.ok)
                pip_box(g, style, loc, D_PIN_X, chan_y(loc, cs));
            else if (src_id == GFX_WIRE_XB) // Direkt von X darunter
                pip_box(g, style, loc, D_PIN_X, XB_D_Y);
            else if (src_id == GFX_WIRE_PB) // Pad darunter: auf seiner Stichleitung
                pip_box(g, style, loc, D_PIN_X, pad_stub(src, loc));
            return;
        case GFX_WIRE_K: // long.2 (Spalte A: long.4) und GCLK
            if (cs.ok)
                pip_box(g, style, loc, chan_x(loc, cs, -1), K_LINE);
            return;
        }
        // CLB-Ausgänge -> Kanal rechts
        if ((src_id == GFX_WIRE_X || src_id == GFX_WIRE_Y) && cd.ok) {
            pip_box(g, style, loc, chan_x(loc, cd, -1), src_id == GFX_WIRE_X ? X_Y : Y_Y);
            return;
        }

        // IOB: Kästchen, wo ein Pin bzw. seine Stichleitung eine Leitung kreuzt (beim Taktpuffer die
        // Taktleitung); X/Y direkt am Eingang des Ausgangsmultiplexers
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
