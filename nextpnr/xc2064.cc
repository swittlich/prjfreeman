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
#include <tuple>

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

struct Xc2064Impl : HimbaechelAPI
{
    ~Xc2064Impl() {};

    po::options_description getUArchOptions()
    {
        po::options_description specific("XC2064 specific options");
        specific.add_options()("pcf", po::value<std::string>(),
                               "PCF file with pin constraints: set_io [-nowarn] <port> <pin> (PLCC68 pins P2..P68)");
        return specific;
    }

    void init_database(Arch *arch) override
    {
        init_uarch_constids(arch);
        arch->load_chipdb("xc2064/chipdb-xc2064.bin");
        arch->set_speed_grade("DEFAULT");
    }

    void init(Context *ctx) override
    {
        h.init(ctx);
        HimbaechelAPI::init(ctx);
        // Pads nach PLCC68-Pin (Bel-Name) und die beiden Taktpins
        for (BelId bel : ctx->getBels()) {
            if (ctx->getBelType(bel) != id_IOB)
                continue;
            pad_bels[ctx->getBelName(bel)[1]] = bel;
            // Randkanalstück, an dem das IOB hängt (wie pad_info() im Generator), für die Grafik
            Loc l = ctx->getBelLocation(bel);
            char side = io_side(l);
            int idx = (side == 'T' || side == 'B') ? l.x : l.y;
            iob_slots.insert({side, idx - l.z, l.z});
        }
        clock_pads = {pad_bels.at(ctx->id("P9")), pad_bels.at(ctx->id("P43"))};
    }

    // Das Routing des XC2064 ist knapp (4 Spuren je Kanal, 81 Kreuzungen): router2 löst Überlastung
    // zuverlässiger als router1 (wie bei gatemate/xilinx). "--router router1" bleibt möglich.
    std::string getDefaultRouter() const override { return "router2"; }

    // XC2000_INBUF bzw. XC2000_OUTBUF, dessen PAD am Top-Level-Port (Zelle $nextpnr_*buf) hängt
    static CellInfo *io_buffer(CellInfo *port)
    {
        auto is_buf = [](const PortRef &r) {
            return r.cell && r.cell->type.in(id_XC2000_INBUF, id_XC2000_OUTBUF) && r.port == id_PAD;
        };
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
                log_error("%s:%d: '%s' ist kein XC2064-Pad (PLCC68: P2..P68)\n", file.c_str(), lineno,
                          pin_name.c_str());
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
                log_error("%s:%d: Port '%s' hat keinen XC2000_INBUF/XC2000_OUTBUF (synth_xc2064 -noiopad?)\n",
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

    // Pins aus PCF bzw. (* LOC="P9" *) am XC2000_INBUF/XC2000_OUTBUF: das IOB schon beim Packen fest
    // belegen (wie GateMate), damit die GUI nach "Pack" die belegten Pads zeigt. Ein BEL-Attribut
    // bleibt dabei weg, sonst würde der Placer die Zelle ein zweites Mal binden wollen.
    void bind_constrained_pads()
    {
        int bound = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            auto loc = ci->attrs.find(id_LOC);
            if (!ci->type.in(id_XC2000_INBUF, id_XC2000_OUTBUF) || loc == ci->attrs.end())
                continue;
            IdString pin = ctx->id(loc->second.as_string());
            if (!pad_bels.count(pin))
                log_error("%s: LOC \"%s\" ist kein XC2064-Pad (PLCC68: P2..P68)\n", ci->name.c_str(ctx),
                          pin.c_str(ctx));
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
            if (!drv || drv->type != id_XC2000_INBUF)
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
            if (!ctx->checkBelAvail(pad))
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
        };
        h.remove_nextpnr_iobs(top_ports);
        bind_constrained_pads();
        bind_clock_pads();
        h.replace_constants(CellTypePort(id_VCC_DRV, id_VCC), CellTypePort(id_GND_DRV, id_GND), {}, {}, id_VCC,
                            id_GND);
        int moved = route_q_feedback_to_i2();
        // Das FF bekommt seine Daten nur aus F bzw. FG derselben CLB. synth_xc2064 sorgt dafür, dass
        // jedes FF einen eigenen LUT hat; LUT und FF werden hier als Cluster gemeinsam platziert.
        const pool<CellTypePort> ff_d{{id_XC2000_DFF, id_D}};
        int n3 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT3, id_O}}, ff_d, Z_FF - Z_F);
        int n4 = h.constrain_cell_pairs(pool<CellTypePort>{{id_XC2000_LUT4, id_O}}, ff_d, Z_FF - Z_FG);
        log_info("Constrained %d LUT3/FF and %d LUT4/FF pairs, %d Q feedback inputs moved to I[2].\n", n3, n4,
                 moved);
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
            return id_IOB;
        }
        return cell_type; // GND_DRV, VCC_DRV
    }

    IdString getBelBucketForCellType(IdString cell_type) const override { return bel_type_for(cell_type); }

    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == bel_type_for(cell_type);
    }

  private:
    HimbaechelHelpers h;
    dict<IdString, BelId> pad_bels;
    std::array<BelId, 2> clock_pads;            // P9 (GCLK), P43 (ACLK)
    std::set<std::tuple<char, int, int>> iob_slots; // (Seite, Randkanalstück, z) mit IOB

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

    bool is_global_clock(const NetInfo *net) const
    {
        const CellInfo *drv = net->driver.cell;
        if (!drv || drv->type != id_XC2000_INBUF)
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
            if ((opts & M(S_K)) && !is_global_clock(net))
                opts &= ~M(S_K);
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
    }

    // --- GUI: Schaltplan ----------------------------------------------------------------------
    // Kachel-Koordinaten 0..1 mit y nach unten (wie Datenblatt und Die-Fotos, X0Y0 oben links). Die
    // nextpnr-GUI zeichnet mit y nach oben, darum spiegeln box()/line() an der Horizontalen.
    //
    // Routing: oben links die Switch-Matrizen SM0/SM1, rechts davon der Kanal oberhalb der CLB, darunter
    // der Kanal links der CLB (je 4 Spuren), dazu Long Lines (LH, LV0/LV1) und die Taktnetze GCLK/ACLK.
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

    static float sm_lo(int m) { return 0.02 + 0.1 * m; }
    static float sm_hi(int m) { return 0.13 + 0.1 * m; }
    static float trk(int t) { return 0.05 + 0.05 * t; } // Spur t = 2m+k: 0,1 -> SM0, 2,3 -> SM1

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
    static constexpr float LV0_X = 0.27, LV1_X = 0.30, DIR_X = 0.31, YL_X = 0.32;
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

    // --- Routing- und IO-Geometrie (für Kanalspuren, Long Lines, Pads) ---
    enum GKind
    {
        G_NONE,
        G_POINT,
        G_HTRACK, // y fest, x in [a, b]
        G_VTRACK, // x fest, y in [a, b]
    };
    struct Geom
    {
        GKind kind = G_NONE;
        float x = 0, y = 0, a = 0, b = 0;
    };
    static Geom point(float x, float y) { return Geom{G_POINT, x, y, 0, 0}; }
    static Geom htrack(float y, float a, float b) { return Geom{G_HTRACK, 0, y, a, b}; }
    static Geom vtrack(float x, float a, float b) { return Geom{G_VTRACK, x, 0, a, b}; }

    static bool is_sm_pin(int32_t id) { return id >= GFX_WIRE_SM0_N0 && id <= GFX_WIRE_SM1_W1; }
    // Switch-Matrix-Pin: Matrix m, Seite (0=N, 1=E, 2=S, 3=W), Spur t
    static void sm_pin(int32_t id, int &m, int &side, int &t)
    {
        int d = id - GFX_WIRE_SM0_N0;
        m = d / 8;
        side = (d % 8) / 2;
        t = 2 * m + d % 2;
    }
    static float sm_pin_x(int m, int side, int t)
    {
        return side == 0 || side == 2 ? trk(t) : side == 1 ? sm_hi(m) : sm_lo(m);
    }
    static float sm_pin_y(int m, int side, int t)
    {
        return side == 1 || side == 3 ? trk(t) : side == 2 ? sm_hi(m) : sm_lo(m);
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
    Geom geom(Loc loc, int32_t id) const
    {
        if (is_sm_pin(id)) {
            int m, side, t;
            sm_pin(id, m, side, t);
            switch (side) {
            case 0: // N: Segment nach oben
                return vtrack(trk(t), -1 + sm_hi(m), sm_lo(m));
            case 1: // E
                return htrack(trk(t), sm_hi(m), 1 + sm_lo(m));
            case 2: // S
                return vtrack(trk(t), sm_hi(m), 1 + sm_lo(m));
            default: // W
                return htrack(trk(t), -1 + sm_hi(m), sm_lo(m));
            }
        }
        switch (id) {
        case GFX_WIRE_LH: // über das Routing-Feld bis über den Randkanal rechts
            return htrack(0.27, 0.0, loc.x == LAST ? 0.33 : 1.0);
        case GFX_WIRE_LV0: // ... bzw. unten
        case GFX_WIRE_LV1:
            return vtrack(id == GFX_WIRE_LV0 ? LV0_X : LV1_X, 0.0, loc.y == LAST ? 0.33 : 1.0);
        case GFX_WIRE_GCLK_SRC: // P9 oben links -> GCLK-Leitung in der CLB darunter
            return point(0.33, 1.0);
        case GFX_WIRE_ACLK_SRC: // P43 unten rechts -> ACLK-Leitung in der CLB links oberhalb
            return point(-0.655, 0.0);
        }
        return Geom{};
    }

    // --- IOB-Geometrie ---
    // Ein IOB hängt wie im Original am Kanalstück parallel zum Rand: oben/unten am waagerechten Kanal
    // über der ersten bzw. unter der letzten CLB-Zeile, links/rechts am senkrechten Kanal der ersten bzw.
    // letzten Spalte. Ein Kanalstück neben einer CLB trägt bis zu zwei IOBs: das erste Pad seiner
    // Kachel (z = 0) in der ersten Hälfte, das zweite Pad der folgenden Kachel (z = 1) in der zweiten.
    // Koordinaten: r entlang des Rands ab dem Anfang des IOB, d vom Chiprand nach innen. Aufbau wie im
    // Datenblatt, von außen nach innen: Pad; Ausgangstreiber (Dreieck zum Pad) und Eingangstreiber
    // (Dreieck nach innen); Multiplexer für den Ausgang (Bel-Pin I, im Datenblatt "O") und das Tristate
    // T; dann laufen die Leitungen von Ausgang, T und Eingang (Bel-Pin O, im Datenblatt "I") quer über
    // das Kanalstück. Direktverbindungen: X (rechts auch Y) der Rand-CLB läuft gerade in den
    // Ausgangsmultiplexer (oben/unten ist das zweite IOB dafür gespiegelt), der Eingang vom Pad läuft
    // links, oben und unten weiter zu B bzw. C/D der Rand-CLB (auf den Wegen, die dort sonst die
    // Direktleitungen von X und Y der fehlenden Nachbar-CLB nehmen).
    static constexpr float IOB_U0 = 0.385, IOB_DU = 0.3135, IOB_W = 0.27; // Lage am Kanalstück, Breite
    static constexpr float IOB_D0 = 0.18, IOB_D1 = 0.58;                 // Rahmen
    static constexpr float PAD_R = 0.135, PAD_HW = 0.04, PAD_D0 = 0.03, PAD_D1 = 0.11, JCT_D = 0.22;
    static constexpr float OB_R = 0.07, OB_TIP = 0.28, OB_BASE = 0.36;  // Ausgangstreiber
    static constexpr float IB_R = 0.235, IB_BASE = 0.26, IB_TIP = 0.34; // Eingangstreiber
    static constexpr float OM_R0 = 0.012, OM_R1 = 0.13, TM_R0 = 0.15, TM_R1 = 0.20; // Multiplexer
    static constexpr float MX_D0 = 0.44, OM_D1 = 0.52, TM_D1 = 0.50, EN_D = 0.32;
    static constexpr float O_R = 0.07, T_R = 0.175, I_R = IB_R; // Leitungen über den Kanal
    static constexpr float DX_R = 0.0265, DY_R = 0.115;         // X, Y direkt (rechter Rand)

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
    // Punkt im IOB (d ohne Versatz) in Kachel-Koordinaten; Lagen im Kanal vorher um b.off verringern
    static std::pair<float, float> iob_pt(const Iob &b, float r, float d)
    {
        float u = b.mirror ? b.u0 + IOB_W - r : b.u0 + r;
        d += b.off;
        switch (b.side) {
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
    // r zu einer Lage u entlang des Rands (in der eigenen Kachel)
    static float iob_r(const Iob &b, float u) { return b.mirror ? IOB_W - (u - b.u0) : u - b.u0; }
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
    // Lage der Spuren und Long Lines des Randkanalstücks und Ende der Leitungen dahinter
    static float iob_track_d(char s, int t) { return (s == 'T' || s == 'L') ? 1 + trk(t) : 1 - trk(t); }
    static float iob_long_d(char s, int32_t id)
    {
        float v = id == GFX_WIRE_LV1 ? LV1_X : 0.27; // LH und LV0 bei 0.27
        return (s == 'T' || s == 'L') ? 1 + v : 1 - v;
    }
    static float iob_end_d(char s) { return s == 'T' ? 1.28f : s == 'L' ? 1.305f : 0.97f; }
    bool has_iob(char side, int seg, int z) const { return iob_slots.count({side, seg, z}) > 0; }
    // CLB der letzten Spalte mit IOB rechts daneben, das X und Y direkt nimmt
    bool right_iob(Loc loc) const { return loc.x == ctx->getGridDimX() - 2 && has_iob('R', loc.y, 0); }

    void drawGroup(std::vector<GraphicElement> &g, GroupId group, Loc loc) override
    {
        IdString type = ctx->getGroupType(group);
        if (type == id_SWITCHBOX) {
            int m = group.index; // SM0 bzw. SM1
            box(g, GraphicElement::STYLE_FRAME, loc.x + sm_lo(m), loc.y + sm_lo(m), loc.x + sm_hi(m),
                loc.y + sm_hi(m));
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
        case id_GND_DRV.index:
        case id_VCC_DRV.index:
            box(g, style, x + 0.40 + loc.z * 0.25, y + 0.50, x + 0.58 + loc.z * 0.25, y + 0.68);
            break;
        }
    }

    void drawWire(std::vector<GraphicElement> &g, GraphicElement::style_t style, Loc loc, IdString wire_type,
                  int32_t tilewire, IdString tile_type) override
    {
        float x = loc.x, y = loc.y;

        // CLB: Multiplexer mit Ausgang zum Bel bzw. zum Pin
        bool is_mux = for_muxes(tilewire, [&](const Mux &m) {
            float ox = mux_x(m) + MUX_W, oy = mux_out_y(m);
            draw_mux(g, style, loc, mux_x(m), m.y_top, ox, mux_bot(m));
            switch (m.out) {
            case GFX_WIRE_X: // durch den Kanal rechts bis zur Long Line (am Rand ins IOB), Direktleitungen
                poly(g, style, loc,
                     {{ox, oy}, {right_iob(loc) ? 2 - OM_D1 : 1 + LV0_X + 0.01, oy}});
                if (loc.y > 1) { // zu D und C der CLB darüber
                    poly(g, style, loc,
                         {{X_UP_X, oy}, {X_UP_X, XB_C_Y - 1}, {DIR_X, XB_C_Y - 1}, {DIR_X, C_ROW - 1}});
                    poly(g, style, loc, {{X_UP_X, XB_D_Y - 1}, {D_PIN_X, XB_D_Y - 1}});
                    dot(g, style, loc, X_UP_X, oy);
                    dot(g, style, loc, X_UP_X, XB_D_Y - 1);
                } else if (has_iob('T', loc.x, 1)) { // in den Ausgangsmultiplexer des IOB darüber
                    poly(g, style, loc, {{X_UP_X, oy}, {X_UP_X, -1 + 0.30f + OM_D1}});
                    dot(g, style, loc, X_UP_X, oy);
                }
                if (loc.y < ctx->getGridDimY() - 2) { // zu A und B der CLB darunter
                    poly(g, style, loc,
                         {{X_DN_X, oy}, {X_DN_X, 1 + XT_B_Y}, {DIR_X, 1 + XT_B_Y}, {DIR_X, 1 + B_ROW}});
                    poly(g, style, loc, {{X_DN_X, 1 + XT_A_Y}, {A_PIN_X, 1 + XT_A_Y}});
                    dot(g, style, loc, X_DN_X, oy);
                    dot(g, style, loc, X_DN_X, 1 + XT_A_Y);
                } else if (has_iob('B', loc.x, 1)) { // in den Ausgangsmultiplexer des IOB darunter
                    poly(g, style, loc, {{X_DN_X, oy}, {X_DN_X, 2 - OM_D1}});
                    dot(g, style, loc, X_DN_X, oy);
                }
                break;
            case GFX_WIRE_Y: // durch den Kanal rechts, weiter zu B der Nachbar-CLB
                if (loc.x < ctx->getGridDimX() - 2)
                    poly(g, style, loc, {{ox, oy}, {1 + YL_X, oy}, {1 + YL_X, B_ROW}});
                else
                    poly(g, style, loc, {{ox, oy}, {right_iob(loc) ? 2 - OM_D1 : 1 + LV1_X + 0.01, oy}});
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
        case GFX_WIRE_K: // von GCLK/ACLK
            poly(g, style, loc, {{0.33, K_LINE}, {K_END_X, K_LINE}});
            return;
        case GFX_WIRE_F_O:
        case GFX_WIRE_G_O:
        case GFX_WIRE_FG_O: { // Ausgang -> Verteiler, über dem Speicherelement -> Ausgangsschiene
            auto src = source_point(tilewire);
            float vx = src_x(COL_FF, tilewire), rx = src_x(COL_OUT, tilewire), ry = row_y(tilewire), rtop, rbot;
            taps(tilewire, false, top, bot);
            taps(tilewire, true, rtop, rbot);
            top = std::min({top, ry, src.second}), bot = std::max({bot, ry, src.second});
            rtop = std::min(rtop, ry), rbot = std::max(rbot, ry);
            poly(g, style, loc, {src, {vx, src.second}});
            poly(g, style, loc, {{vx, top}, {vx, bot}});
            poly(g, style, loc, {{vx, ry}, {rx, ry}});
            poly(g, style, loc, {{rx, rtop}, {rx, rbot}});
            tee(vx, src.second, top, bot);
            tee(vx, ry, top, bot);
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
        case GFX_WIRE_GCLK:
            poly(g, style, loc, {{0.33, 0}, {0.33, 1}});
            return;
        case GFX_WIRE_ACLK:
            poly(g, style, loc, {{0.345, 0}, {0.345, 1}});
            return;
        case GFX_WIRE_XT: // Teile von Knoten, die eine Nachbarkachel zeichnet
        case GFX_WIRE_XB:
        case GFX_WIRE_YL:
        case GFX_WIRE_LHB:
        case GFX_WIRE_RLV0:
        case GFX_WIRE_RLV1:
        case GFX_WIRE_PL:
        case GFX_WIRE_PT:
        case GFX_WIRE_PB:
            return;
        }

        // IOB: Multiplexer und Leitungen der Pins über das Randkanalstück
        if (tilewire >= GFX_WIRE_IO0_I && tilewire <= GFX_WIRE_IO1_T) {
            int z = (tilewire - GFX_WIRE_IO0_I) / 3, p = (tilewire - GFX_WIRE_IO0_I) % 3; // I, O, T
            Iob b = iob(loc, z);
            float de = iob_end_d(b.side) - b.off;
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
                // ... und direkt zur Rand-CLB (d hier ohne Versatz, s. iob_pt)
                if (b.side == 'T' && z == 0) { // -> B der CLB darunter
                    float dd = 1 + XT_B_Y - b.off, rx = iob_r(b, DIR_X);
                    iob_line(g, style, loc, b, {{I_R, de}, {I_R, dd}, {rx, dd}, {rx, 1 + B_ROW - b.off}});
                } else if (b.side == 'B' && z == 0) { // -> D und C der CLB darüber
                    float dd = 2 - XB_D_Y, dc = 2 - XB_C_Y, rc = iob_r(b, DIR_X);
                    iob_line(g, style, loc, b, {{I_R, de}, {I_R, dc}, {rc, dc}, {rc, 2 - C_ROW}});
                    iob_line(g, style, loc, b, {{I_R, dd}, {iob_r(b, D_PIN_X), dd}});
                    iob_dot(g, style, loc, b, I_R, dd);
                } else if (b.side == 'L' && z == 1) { // -> B der CLB rechts (Zeile darüber)
                    float dd = 1 + YL_X - b.off;
                    iob_line(g, style, loc, b, {{I_R, de}, {I_R, dd}, {iob_r(b, B_ROW - 1), dd}});
                }
                for (int c = 0; c < 2; c++) { // Taktpuffer: P9 (oben) speist GCLK, P43 (unten) ACLK
                    Loc cl = ctx->getBelLocation(clock_pads[c]);
                    if (cl.x != loc.x || cl.y != loc.y || cl.z != z)
                        continue;
                    Geom tp = geom(loc, c ? GFX_WIRE_ACLK_SRC : GFX_WIRE_GCLK_SRC);
                    float bd = (b.side == 'T' ? 0.97f : 0.67f) - b.off, tr = iob_r(b, tp.x); // Taktleitung bei d = 1
                    iob_line(g, style, loc, b, {{I_R, bd}, {tr, bd}, {tr, 1 - b.off}});
                    iob_dot(g, style, loc, b, I_R, bd);
                }
            }
            return;
        }

        // Routing und IO
        if (is_sm_pin(tilewire)) {
            // Segmente zeichnet ihr Anfang (E bzw. S). Am Rand enden die Matrizen (wie im Original).
            int mm, side, t;
            sm_pin(tilewire, mm, side, t);
            if (side == 0 || side == 3 || (side == 1 && loc.x == LAST) || (side == 2 && loc.y == LAST))
                return;
        } else if ((tilewire >= GFX_WIRE_BOT00 && tilewire <= GFX_WIRE_RGT11) ||
                   (tilewire >= GFX_WIRE_IO0_T00 && tilewire <= GFX_WIRE_IO1_T11) || tilewire == GFX_WIRE_IO0_X ||
                   tilewire == GFX_WIRE_IO0_Y || tilewire == GFX_WIRE_IO1_X) {
            return; // Teil eines Knotens, den eine andere Kachel zeichnet
        } else if ((tilewire == GFX_WIRE_LH || tilewire == GFX_WIRE_LV0 || tilewire == GFX_WIRE_LV1) &&
                   (loc.x == 0 || loc.y == 0)) {
            return; // Zugang der Pads oben/links zur Long Line des Randkanals
        }
        Geom gm = geom(loc, tilewire);
        switch (gm.kind) {
        case G_HTRACK:
            line(g, style, x + gm.a, y + gm.y, x + gm.b, y + gm.y);
            break;
        case G_VTRACK:
            line(g, style, x + gm.x, y + gm.a, x + gm.x, y + gm.b);
            break;
        case G_POINT: // Taktpuffer: kleine Markierung
            line(g, style, x + gm.x - 0.008, y + gm.y, x + gm.x + 0.008, y + gm.y);
            line(g, style, x + gm.x, y + gm.y - 0.008, x + gm.x, y + gm.y + 0.008);
            break;
        default:
            break;
        }
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

        // Switch-Matrix: Verbindung von Pin zu Pin
        if (is_sm_pin(src_id) && is_sm_pin(dst_id)) {
            int m, s1, t1, s2, t2;
            sm_pin(src_id, m, s1, t1);
            sm_pin(dst_id, m, s2, t2);
            poly(g, style, loc, {{sm_pin_x(m, s1, t1), sm_pin_y(m, s1, t1)}, {sm_pin_x(m, s2, t2), sm_pin_y(m, s2, t2)}});
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

        int m_, side, t;
        // Routing -> CLB-Eingänge
        switch (dst_id) {
        case GFX_WIRE_A: // Pin kreuzt den Kanal oberhalb
            if (is_sm_pin(src_id)) { // E-Pins
                sm_pin(src_id, m_, side, t);
                pip_box(g, style, loc, A_PIN_X, trk(t));
            } else if (src_id == GFX_WIRE_LH) {
                pip_box(g, style, loc, A_PIN_X, 0.27);
            } else if (src_id == GFX_WIRE_XT) { // Direktverbindung von X der CLB darüber
                pip_box(g, style, loc, A_PIN_X, XT_A_Y);
            }
            return;
        case GFX_WIRE_B:
        case GFX_WIRE_C: { // Zeilen kreuzen den Kanal links
            float py = dst_id == GFX_WIRE_B ? B_ROW : C_ROW;
            if (is_sm_pin(src_id)) { // S-Pins
                sm_pin(src_id, m_, side, t);
                pip_box(g, style, loc, trk(t), py);
            } else if (src_id == GFX_WIRE_LV0 || src_id == GFX_WIRE_LV1) {
                pip_box(g, style, loc, src_id == GFX_WIRE_LV0 ? LV0_X : LV1_X, py);
            } else if (src_id == GFX_WIRE_XT || src_id == GFX_WIRE_XB || src_id == GFX_WIRE_PT ||
                       src_id == GFX_WIRE_PB) { // Direktverbindung von X bzw. Pad darüber/darunter
                pip_box(g, style, loc, DIR_X, py);
            } else if (src_id == GFX_WIRE_PL) { // Direktverbindung vom Pad links
                pip_box(g, style, loc, YL_X, py);
            } else if (src_id == GFX_WIRE_YL) { // Direktverbindung von Y der CLB links
                pip_box(g, style, loc, YL_X, py);
            }
            return;
        }
        case GFX_WIRE_D: // Pin kreuzt den Kanal und die Long Line unterhalb
            if (src_id >= GFX_WIRE_BOT00 && src_id <= GFX_WIRE_BOT11) {
                pip_box(g, style, loc, D_PIN_X, 1 + trk(src_id - GFX_WIRE_BOT00));
            } else if (src_id == GFX_WIRE_LHB) {
                pip_box(g, style, loc, D_PIN_X, 1.27);
            } else if (src_id == GFX_WIRE_XB || src_id == GFX_WIRE_PB) { // Direkt von X bzw. Pad darunter
                pip_box(g, style, loc, D_PIN_X, XB_D_Y);
            }
            return;
        case GFX_WIRE_K: // globale Taktnetze
            pip_box(g, style, loc, src_id == GFX_WIRE_GCLK ? 0.33 : 0.345, K_LINE);
            return;
        }
        // CLB-Ausgänge -> Routing
        if (src_id == GFX_WIRE_X || src_id == GFX_WIRE_Y) { // Kanal und Long Lines rechts
            float oy = src_id == GFX_WIRE_X ? X_Y : Y_Y;
            if (dst_id >= GFX_WIRE_RGT00 && dst_id <= GFX_WIRE_RGT11)
                pip_box(g, style, loc, 1 + trk(dst_id - GFX_WIRE_RGT00), oy);
            else if (dst_id == GFX_WIRE_RLV0 || dst_id == GFX_WIRE_RLV1)
                pip_box(g, style, loc, 1 + (dst_id == GFX_WIRE_RLV0 ? LV0_X : LV1_X), oy);
            return;
        }

        // IOB: Kästchen, wo die Leitung eines Pins Spur, Long Line oder X/Y trifft; Taktpuffer
        int32_t pin = (src_id >= GFX_WIRE_IO0_I && src_id <= GFX_WIRE_IO1_T) ? src_id : dst_id;
        if (pin < GFX_WIRE_IO0_I || pin > GFX_WIRE_IO1_T)
            return;
        int z = (pin - GFX_WIRE_IO0_I) / 3, p = (pin - GFX_WIRE_IO0_I) % 3;
        int32_t other = pin == src_id ? dst_id : src_id;
        Iob b = iob(loc, z);
        float r = p == 0 ? O_R : p == 1 ? I_R : T_R, d;
        if (other >= GFX_WIRE_IO0_T00 && other <= GFX_WIRE_IO1_T11) {
            d = iob_track_d(b.side, (other - GFX_WIRE_IO0_T00) % 4) - b.off;
        } else if (other == GFX_WIRE_LH || other == GFX_WIRE_LV0 || other == GFX_WIRE_LV1) {
            d = iob_long_d(b.side, other) - b.off;
        } else if (other == GFX_WIRE_IO0_X || other == GFX_WIRE_IO0_Y) {
            r = other == GFX_WIRE_IO0_X ? DX_R : DY_R, d = OM_D1 + 0.012;
        } else if (other == GFX_WIRE_IO1_X) { // X der Rand-CLB oben/unten (Kachel daneben)
            r = iob_r(b, (b.side == 'T' ? X_UP_X : X_DN_X) - 1), d = OM_D1 + 0.012;
        } else if (other == GFX_WIRE_GCLK_SRC || other == GFX_WIRE_ACLK_SRC) {
            r = iob_r(b, geom(loc, other).x), d = 0.985f - b.off;
        } else {
            return; // Konstanten GND/VCC
        }
        auto q = iob_pt(b, r, d);
        pip_box(g, style, loc, q.first, q.second);
    }
};

struct Xc2064Arch : HimbaechelArch
{
    Xc2064Arch() : HimbaechelArch("xc2064") {};
    bool match_device(const std::string &device) override { return device == "XC2064" || device == "xc2064"; }
    std::unique_ptr<HimbaechelAPI> create(const std::string &device) override
    {
        return std::make_unique<Xc2064Impl>();
    }
} xc2064Arch;

} // namespace

NEXTPNR_NAMESPACE_END
