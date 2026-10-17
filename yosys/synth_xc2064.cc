/*
 * synth_xc2064 – Yosys-Synthese für das XC2064-Modell (als Plugin).
 *
 * Erzeugt die Zellen, die die nextpnr-Himbächel-uarch "xc2064" erwartet:
 *   XC2000_LUT3   (I[2:0] -> O, INIT[7:0])   Funktionsgenerator F oder G
 *   XC2000_LUT4   (I[3:0] -> O, INIT[15:0])  F und G gemeinsam (Funktion von 4 Variablen)
 *   XC2000_FGM    (F[2:0], G[2:0], S -> O, INIT_F, INIT_G)  Mux-Modus: S (= B) wählt zwischen F und G
 *   XC2000_DFF    (CLK, D, S, R -> Q)        das Speicherelement der CLB (FF oder Latch, Parameter
 *                                            LATCH, CLKINV), Daten nur aus F/FG/FGM, asynchrones Set/Reset
 *   XC2000_INBUF  (PAD -> O), XC2000_OUTBUF (I -> PAD)
 *   XC2000_INFF   (PAD, K -> O)              gelatchter Eingang: FF im IOB, Takt K von der Leitung der Seite
 *   XC2000_TOBUF  (I, T -> PAD), XC2000_IOBUF (I, T -> PAD -> O)   Tristate, T = 1 schaltet ab
 * Präfix XC2000_ für die Familie (wie CC_ bei GateMate).
 *
 * Zusätzlich die Pässe xc2064_fgm (LUTs vor einem FF zum Mux-Modus FGM zusammenfassen), xc2064_iobff (FF hinter
 * einem Eingang ins IOB legen) und xc2064_ffbuf (jedem FF einen eigenen treibenden LUT geben).
 *
 *   yosys -m arch/xc2064/yosys/build/xc2064.so -p "synth_xc2064 -json out.json" design.v
 */

#include "kernel/yosys.h"
#include "kernel/sigtools.h"

#ifndef FAT_ARCH_DATDIR
#error "FAT_ARCH_DATDIR fehlt – das Plugin über das Makefile bauen"
#endif

USING_YOSYS_NAMESPACE
PRIVATE_NAMESPACE_BEGIN

// Im XC2064 kommen die FF-Daten nur aus dem Funktionsgenerator F derselben CLB. Jedes FF braucht
// daher einen LUT, der sonst kein anderes FF speist. Fehlt der (D direkt von einem Eingang, einem
// anderen FF oder einer Konstante) oder ist er schon vergeben, wird ein XC2000_LUT3-Puffer eingesetzt.
struct Xc2064FfBufPass : public Pass
{
	Xc2064FfBufPass() : Pass("xc2064_ffbuf", "XC2064: give every XC2000_DFF its own driving LUT") {}

	void help() override
	{
		//   |---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|
		log("\n");
		log("    xc2064_ffbuf [selection]\n");
		log("\n");
		log("In the XC2064 the flip-flop data input is fed only by the F function generator of\n");
		log("the same CLB. This pass inserts an XC2000_LUT3 buffer (INIT 8'hAA, O = I[0]) in\n");
		log("front of every XC2000_DFF whose D input is not driven exclusively by an\n");
		log("XC2000_LUT3/XC2000_LUT4/XC2000_FGM.\n");
		log("\n");
	}

	void execute(std::vector<std::string> args, RTLIL::Design *design) override
	{
		log_header(design, "Executing XC2064_FFBUF pass.\n");
		extra_args(args, 1, design);

		// Eigene Zelltypen stehen nicht in yosys' kernel/constids.inc (ID(...) geht nur dafür),
		// sondern werden im TwinePool des Designs angelegt.
		TwinePool &tw = design->twines();
		const IdString lut3 = tw.add("\\XC2000_LUT3"), lut4 = tw.add("\\XC2000_LUT4"), fgm = tw.add("\\XC2000_FGM");
		const IdString dff = tw.add("\\XC2000_DFF");

		int inserted = 0;
		for (auto module : design->selected_modules()) {
			SigMap sigmap(module);
			dict<SigBit, Cell *> lut_driver;
			for (auto cell : module->cells())
				if (cell->type.in(lut3, lut4, fgm))
					for (auto bit : sigmap(cell->getPort(ID(O))))
						lut_driver[bit] = cell;

			pool<Cell *> claimed;
			for (auto cell : module->selected_cells()) {
				if (cell->type != dff)
					continue;
				SigBit d = sigmap(cell->getPort(ID(D))).as_bit();
				auto it = lut_driver.find(d);
				if (it != lut_driver.end() && !claimed.count(it->second)) {
					claimed.insert(it->second);
					continue;
				}
				Wire *w = module->addWire(NEW_ID);
				Cell *buf = module->addCell(NEW_ID, lut3);
				buf->setParam(ID(INIT), Const(0xAA, 8));
				SigSpec in;
				in.append(d);
				in.append(State::Sx);
				in.append(State::Sx);
				buf->setPort(ID(I), in);
				buf->setPort(ID(O), w);
				cell->setPort(ID(D), w);
				claimed.insert(buf);
				inserted++;
			}
		}
		log("Inserted %d XC2000_LUT3 buffers in front of flip-flops.\n", inserted);
	}
} Xc2064FfBufPass;

// Mux-Modus FGM (Data Book: "Option 3"): B wählt zwischen den Tabellen F und G, die hier eigene Eingänge haben
// (je 1 aus A/B, 2 aus B/C, 3 aus C/D/Q). Gegenüber einer Funktion von 4 Variablen gewinnt das nur, wenn eine
// Tabelle D und die andere das Q des eigenen Speicherelements liest: D und Q gehen nie in dieselbe Tabelle.
// Nach dem LUT-Mapping fasst der Pass daher den LUT vor einem Speicherelement mit LUTs davor (die nur ihn
// speisen) zusammen, wenn das Ganze eine Funktion von genau 5 Signalen ist, darunter das eigene Q, und die
// Form S ? f(a, c, x) : g(a, c, Q) hat (oder F und G vertauscht). Daraus wird ein XC2000_FGM: S an B,
// a an Eingang 1, c an Eingang 2, x bzw. Q an Eingang 3.
struct Xc2064FgmPass : public Pass
{
	Xc2064FgmPass() : Pass("xc2064_fgm", "XC2064: merge LUTs in front of a flip-flop into the FGM mux mode") {}

	void help() override
	{
		//   |---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|
		log("\n");
		log("    xc2064_fgm [selection]\n");
		log("\n");
		log("In the FGM mode of an XC2064 CLB the input B selects between the function tables\n");
		log("F and G, each with its own three inputs. This gives functions of five signals of\n");
		log("the form S ? f(a, c, x) : g(a, c, Q), where Q is the CLB's own storage element\n");
		log("(D and Q never feed the same table). For every XC2000_DFF this pass merges the\n");
		log("XC2000_LUT3/XC2000_LUT4 driving D with LUTs in front of it that feed nothing\n");
		log("else, if the result has this form, and replaces them by one XC2000_FGM.\n");
		log("\n");
	}

	// Wert eines Signals für eine Belegung der Blätter (Bit i von env = Blatt i), LUTs aus 'inner' ausgewertet
	static bool eval(SigBit bit, const std::vector<SigBit> &leaves, int env, const dict<SigBit, Cell *> &inner,
			 const SigMap &sigmap)
	{
		for (size_t i = 0; i < leaves.size(); i++)
			if (leaves[i] == bit)
				return (env >> i) & 1;
		if (!bit.wire)
			return bit.data == State::S1; // x: der LUT-Inhalt hängt davon nicht ab
		Cell *lut = inner.at(bit);
		SigSpec in = sigmap(lut->getPort(ID(I)));
		int idx = 0;
		for (int k = 0; k < GetSize(in); k++)
			idx |= int(eval(in[k], leaves, env, inner, sigmap)) << k;
		return lut->getParam(ID(INIT))[idx] == State::S1;
	}

	void execute(std::vector<std::string> args, RTLIL::Design *design) override
	{
		log_header(design, "Executing XC2064_FGM pass.\n");
		extra_args(args, 1, design);

		TwinePool &tw = design->twines();
		const IdString lut3 = tw.add("\\XC2000_LUT3"), lut4 = tw.add("\\XC2000_LUT4"), fgm = tw.add("\\XC2000_FGM");
		const IdString dff = tw.add("\\XC2000_DFF");
		const IdString port_f = tw.add("\\F"), port_g = tw.add("\\G"), port_s = tw.add("\\S");
		const IdString init_f = tw.add("\\INIT_F"), init_g = tw.add("\\INIT_G");

		int merged = 0, removed = 0;
		for (auto module : design->selected_modules()) {
			SigMap sigmap(module);
			dict<SigBit, Cell *> lut_driver;
			dict<SigBit, pool<Cell *>> users; // Zellen, die ein Signal lesen
			pool<SigBit> port_out;            // Signale an Ausgängen des Moduls
			for (auto cell : module->cells())
				for (auto &conn : cell->connections()) {
					if (cell->type.in(lut3, lut4) && conn.first == ID(O))
						for (auto bit : sigmap(conn.second))
							lut_driver[bit] = cell;
					else if (cell->input(conn.first))
						for (auto bit : sigmap(conn.second))
							users[bit].insert(cell);
				}
			for (auto wire : module->wires())
				if (wire->port_output)
					for (auto bit : sigmap(wire))
						port_out.insert(bit);

			pool<Cell *> gone;
			for (auto ff : module->selected_cells()) {
				if (ff->type != dff || gone.count(ff))
					continue;
				SigBit q = sigmap(ff->getPort(ID(Q))).as_bit(), d = sigmap(ff->getPort(ID(D))).as_bit();
				auto ld = lut_driver.find(d);
				if (ld == lut_driver.end() || gone.count(ld->second))
					continue;
				Cell *top = ld->second;
				// LUTs vor dem D-LUT, die nur ihn speisen
				std::vector<SigBit> top_in;
				for (auto bit : sigmap(top->getPort(ID(I))))
					if (bit.wire && std::find(top_in.begin(), top_in.end(), bit) == top_in.end())
						top_in.push_back(bit);
				std::vector<SigBit> cand;
				for (auto bit : top_in) {
					auto it = lut_driver.find(bit);
					if (it != lut_driver.end() && it->second != top && !gone.count(it->second) &&
					    users[bit] == pool<Cell *>{top} && !port_out.count(bit))
						cand.push_back(bit);
				}
				// Teilmengen, die größten zuerst: je mehr LUTs aufgehen, desto besser
				std::vector<int> subsets;
				for (int m = 1; m < (1 << GetSize(cand)); m++)
					subsets.push_back(m);
				std::stable_sort(subsets.begin(), subsets.end(),
						 [](int a, int b) { return __builtin_popcount(a) > __builtin_popcount(b); });
				for (int m : subsets) {
					dict<SigBit, Cell *> inner;
					inner[d] = top;
					for (int k = 0; k < GetSize(cand); k++)
						if ((m >> k) & 1)
							inner[cand[k]] = lut_driver.at(cand[k]);
					std::vector<SigBit> leaves;
					for (auto &it : inner)
						for (auto bit : sigmap(it.second->getPort(ID(I))))
							if (bit.wire && !inner.count(bit) &&
							    std::find(leaves.begin(), leaves.end(), bit) == leaves.end())
								leaves.push_back(bit);
					if (GetSize(leaves) != 5 || std::find(leaves.begin(), leaves.end(), q) == leaves.end())
						continue;
					uint32_t tt = 0;
					for (int env = 0; env < 32; env++)
						tt |= uint32_t(eval(d, leaves, env, inner, sigmap)) << env;
					if (try_fgm(module, top, leaves, tt, q, fgm, port_f, port_g, port_s, init_f, init_g)) {
						for (auto &it : inner)
							gone.insert(it.second);
						merged++;
						removed += GetSize(inner);
						break;
					}
				}
			}
			for (auto cell : gone)
				module->remove(cell);
		}
		log("Merged %d LUTs into %d XC2000_FGM cells.\n", removed, merged);
	}

	// Hängt die Funktion tt der 5 Blätter von Blatt v ab, wenn Blatt s den Wert sv hat?
	static bool depends(uint32_t tt, int s, int sv, int v)
	{
		for (int env = 0; env < 32; env++)
			if (((env >> s) & 1) == sv && !((env >> v) & 1) && ((tt >> env) & 1) != ((tt >> (env | 1 << v)) & 1))
				return true;
		return false;
	}

	static bool try_fgm(Module *module, Cell *top, const std::vector<SigBit> &leaves, uint32_t tt, SigBit q,
			    IdString fgm, IdString port_f, IdString port_g, IdString port_s, IdString init_f, IdString init_g)
	{
		int iq = std::find(leaves.begin(), leaves.end(), q) - leaves.begin();
		for (int s = 0; s < 5; s++) {
			if (s == iq)
				continue;
			for (int x = 0; x < 5; x++) {
				if (x == iq || x == s)
					continue;
				// Tabelle F (S = 1) und G (S = 0): welche liest x, welche Q?
				for (int f_reads_q = 0; f_reads_q < 2; f_reads_q++) {
					int in3_f = f_reads_q ? iq : x, in3_g = f_reads_q ? x : iq;
					if (depends(tt, s, 1, in3_g) || depends(tt, s, 0, in3_f))
						continue;
					std::vector<int> ac; // die beiden übrigen Blätter: Eingang 1 und 2 beider Tabellen
					for (int v = 0; v < 5; v++)
						if (v != s && v != iq && v != x)
							ac.push_back(v);
					Cell *cell = module->addCell(NEW_ID, fgm);
					for (int half = 0; half < 2; half++) { // 0: F (S = 1), 1: G (S = 0)
						int sv = half ? 0 : 1, in[3] = {ac[0], ac[1], half ? in3_g : in3_f};
						uint32_t init = 0;
						for (int idx = 0; idx < 8; idx++) {
							int env = sv << s;
							for (int k = 0; k < 3; k++)
								env |= ((idx >> k) & 1) << in[k];
							init |= ((tt >> env) & 1) << idx;
						}
						SigSpec pins;
						for (int k = 0; k < 3; k++) // nur Eingänge, von denen die Tabelle abhängt
							pins.append(depends(tt, s, sv, in[k]) ? SigSpec(leaves[in[k]]) : SigSpec(State::Sx));
						cell->setPort(half ? port_g : port_f, pins);
						cell->setParam(half ? init_g : init_f, Const(init, 8));
					}
					cell->setPort(port_s, leaves[s]);
					cell->setPort(ID(O), top->getPort(ID(O)));
					return true;
				}
			}
		}
		return false;
	}
} Xc2064FgmPass;

// Gelatchter Eingang (XACT: I:Q, Data Book: "registered input"): das FF im IOB zwischen Pad und Eingang, steigende
// Flanke, Takt von der Taktleitung der Chipseite, ohne Set/Reset. Der Pass legt ein FF dorthin, dessen D direkt
// am Eingang eines Pads hängt, wenn sonst nichts diesen Eingang liest: aus XC2000_INBUF und XC2000_DFF wird ein
// XC2000_INFF. Das spart je Eingang eine CLB.
struct Xc2064IobFfPass : public Pass
{
	Xc2064IobFfPass() : Pass("xc2064_iobff", "XC2064: move input flip-flops into the IOBs") {}

	void help() override
	{
		//   |---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|
		log("\n");
		log("    xc2064_iobff [selection]\n");
		log("\n");
		log("Every IOB of the XC2064 has an edge-triggered D flip-flop between pad and input\n");
		log("(XACT: I:Q), clocked from the clock line of its side of the die. This pass\n");
		log("replaces an XC2000_INBUF and the XC2000_DFF it feeds by one XC2000_INFF if the\n");
		log("flip-flop is the only reader of the pad input, triggers on the rising edge and\n");
		log("has no set/reset.\n");
		log("\n");
	}

	void execute(std::vector<std::string> args, RTLIL::Design *design) override
	{
		log_header(design, "Executing XC2064_IOBFF pass.\n");
		extra_args(args, 1, design);

		TwinePool &tw = design->twines();
		const IdString inbuf = tw.add("\\XC2000_INBUF"), inff = tw.add("\\XC2000_INFF"), dff = tw.add("\\XC2000_DFF");
		const IdString port_pad = tw.add("\\PAD"), port_k = tw.add("\\K"), port_clk = tw.add("\\CLK");
		const IdString port_s = tw.add("\\S"), port_r = tw.add("\\R");
		const IdString latch = tw.add("\\LATCH"), clkinv = tw.add("\\CLKINV");

		int moved = 0;
		for (auto module : design->selected_modules()) {
			SigMap sigmap(module);
			dict<SigBit, int> readers; // lesende Zellen-Ports und Ausgänge des Moduls
			dict<SigBit, Cell *> inbuf_of;
			for (auto cell : module->cells()) {
				if (cell->type == inbuf)
					inbuf_of[sigmap(cell->getPort(ID(O))).as_bit()] = cell;
				for (auto &conn : cell->connections())
					if (cell->input(conn.first))
						for (auto bit : sigmap(conn.second))
							readers[bit]++;
			}
			for (auto wire : module->wires())
				if (wire->port_output)
					for (auto bit : sigmap(wire))
						readers[bit]++;

			auto inactive = [&](Cell *cell, IdString port) { // Set/Reset offen oder konstant aus
				if (!cell->hasPort(port))
					return true;
				for (auto bit : sigmap(cell->getPort(port)))
					if (bit.wire || bit.data == State::S1)
						return false;
				return true;
			};
			for (auto ff : module->selected_cells()) {
				if (ff->type != dff || ff->getParam(latch).as_bool() || ff->getParam(clkinv).as_bool() ||
				    !inactive(ff, port_s) || !inactive(ff, port_r))
					continue;
				SigBit d = sigmap(ff->getPort(ID(D))).as_bit();
				auto it = inbuf_of.find(d);
				if (it == inbuf_of.end() || readers[d] != 1)
					continue;
				Cell *buf = it->second;
				Cell *cell = module->addCell(NEW_ID, inff);
				cell->setPort(port_pad, buf->getPort(port_pad));
				cell->setPort(port_k, ff->getPort(port_clk));
				cell->setPort(ID(O), ff->getPort(ID(Q)));
				inbuf_of.erase(it);
				module->remove(ff);
				module->remove(buf);
				moved++;
			}
		}
		log("Moved %d input flip-flops into IOBs (XC2000_INFF).\n", moved);
	}
} Xc2064IobFfPass;

struct SynthXc2064Pass : public ScriptPass
{
	SynthXc2064Pass() : ScriptPass("synth_xc2064", "synthesis for the XC2064 FPGA model") {}

	void help() override
	{
		//   |---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|---v---|
		log("\n");
		log("    synth_xc2064 [options]\n");
		log("\n");
		log("This command runs synthesis for the XC2064 FPGA model (64 CLBs with two 3-input\n");
		log("function generators F/G, which can be combined into one 4-input function or, with\n");
		log("B selecting, into the FGM mux mode, and one flip-flop fed from F).\n");
		log("\n");
		log("    -top <module>\n");
		log("        use the specified module as top module (default: auto-detect)\n");
		log("\n");
		log("    -json <file>\n");
		log("        write the design to the specified JSON file for nextpnr-himbaechel\n");
		log("\n");
		log("    -noiopad\n");
		log("        do not insert XC2000_INBUF/OUTBUF/TOBUF/IOBUF cells for top-level ports\n");
		log("\n");
		log("    -nofgm\n");
		log("        do not use the FGM mux mode (xc2064_fgm)\n");
		log("\n");
		log("    -noiobff\n");
		log("        keep input flip-flops in the CLBs (xc2064_iobff moves them into the IOBs)\n");
		log("\n");
		log("    -fsm\n");
		log("        let yosys extract and re-encode state machines (default: keep the encoding of\n");
		log("        the RTL, flip-flops are scarce with one per CLB)\n");
		log("\n");
		log("    -run <from_label>:<to_label>\n");
		log("        only run the commands between the labels (see below). an empty\n");
		log("        from label is synonymous to 'begin', and empty to label is\n");
		log("        synonymous to the end of the command list.\n");
		log("\n");
		log("The following commands are executed by this synthesis command:\n");
		help_script();
		log("\n");
	}

	std::string top_opt, json_file;
	bool noiopad, nofgm, noiobff, fsm;

	void clear_flags() override
	{
		top_opt = "-auto-top";
		json_file = "";
		noiopad = false;
		nofgm = false;
		noiobff = false;
		fsm = false;
	}

	void execute(std::vector<std::string> args, RTLIL::Design *design) override
	{
		std::string run_from, run_to;
		clear_flags();

		size_t argidx;
		for (argidx = 1; argidx < args.size(); argidx++) {
			if (args[argidx] == "-top" && argidx + 1 < args.size()) {
				top_opt = "-top " + args[++argidx];
				continue;
			}
			if (args[argidx] == "-json" && argidx + 1 < args.size()) {
				json_file = args[++argidx];
				continue;
			}
			if (args[argidx] == "-noiopad") {
				noiopad = true;
				continue;
			}
			if (args[argidx] == "-nofgm") {
				nofgm = true;
				continue;
			}
			if (args[argidx] == "-noiobff") {
				noiobff = true;
				continue;
			}
			if (args[argidx] == "-fsm") {
				fsm = true;
				continue;
			}
			if (args[argidx] == "-run" && argidx + 1 < args.size()) {
				size_t pos = args[argidx + 1].find(':');
				if (pos == std::string::npos)
					break;
				run_from = args[++argidx].substr(0, pos);
				run_to = args[argidx].substr(pos + 1);
				continue;
			}
			break;
		}
		extra_args(args, argidx, design);

		if (!design->full_selection())
			log_cmd_error("This command only operates on fully selected designs!\n");

		log_header(design, "Executing SYNTH_XC2064 pass.\n");
		log_push();

		run_script(design, run_from, run_to);

		log_pop();
	}

	void script() override
	{
		const std::string datdir = FAT_ARCH_DATDIR;

		if (check_label("begin")) {
			run("read_verilog -lib " + datdir + "/cells_sim.v");
			run(stringf("hierarchy -check %s", help_mode ? "-top <top>" : top_opt.c_str()));
		}

		if (check_label("coarse")) {
			// Tristate: interne Tristate-Netze werden Logik, die an Ports bleiben als $tribuf für
			// iopadmap (wie bei GateMate). inout-Ports, die nur gelesen werden, werden Eingänge.
			run("proc");
			run("flatten");
			run("tribuf -logic");
			run("deminout");
			// Zustandsautomaten behalten ihre Kodierung (yosys kodiert sonst oft one-hot um: beim XC2064 mit
			// einem FF je CLB teuer, und die Register hießen nicht mehr wie im RTL)
			run(fsm || help_mode ? "synth -run coarse:fine" : "synth -nofsm -run coarse:fine",
			    "(-nofsm unless -fsm)");
		}

		if (check_label("fine")) {
			run("opt -fast -full");
			run("memory_map");
			run("opt -full");
			run("techmap");
			run("opt -fast");
			// Speicherelement: FF oder Latch, Takt beliebiger Polarität, asynchrones Set/Reset,
			// nach dem Laden 0. Enables und synchrone Resets werden zu Logik.
			run("dfflegalize -cell $_DFF_P_ 0 -cell $_DFF_N_ 0 -cell $_DFFSR_PPP_ 0 -cell $_DFFSR_NPP_ 0"
			    " -cell $_DLATCH_P_ 0 -cell $_DLATCH_N_ 0 -cell $_DLATCHSR_PPP_ 0 -cell $_DLATCHSR_NPP_ 0");
			run("opt_clean");
		}

		if (check_label("map_io", "(unless -noiopad)")) {
			// Vor dem LUT-Mapping, damit der Inverter für T (T = 1 schaltet ab, $_TBUF_ hat ein
			// Enable) noch in einem LUT aufgeht
			if (!noiopad || help_mode)
				run("iopadmap -bits -inpad XC2000_INBUF O:PAD -outpad XC2000_OUTBUF I:PAD"
				    " -toutpad XC2000_TOBUF ~T:I:PAD -tinoutpad XC2000_IOBUF ~T:O:I:PAD"
				    " -ignore XC2000_INBUF PAD -ignore XC2000_OUTBUF PAD -ignore XC2000_TOBUF PAD"
				    " -ignore XC2000_IOBUF PAD",
				    "(unless -noiopad)");
		}

		if (check_label("map_luts")) {
			// XC2000_LUT3 kostet 1, XC2000_LUT4 kostet 2 (belegt F und G)
			run("abc -lut 3:4 -dress");
			run("opt_clean");
		}

		if (check_label("map_cells")) {
			run("techmap -map " + datdir + "/cells_map.v");
			// Mux-Modus FGM: LUTs vor einem FF mit Rückführung von Q zu einer Funktion von 5 Signalen
			if (!nofgm || help_mode)
				run("xc2064_fgm", "(unless -nofgm)");
			// FF direkt hinter einem Eingang: in das IOB (gelatchter Eingang)
			if (!noiobff || help_mode)
				run("xc2064_iobff", "(unless -noiobff)");
			run("xc2064_ffbuf");
			run("opt_clean");
		}

		if (check_label("check")) {
			run("hierarchy -check");
			run("stat");
			run("check -noinit");
		}

		if (check_label("json")) {
			if (!json_file.empty() || help_mode)
				run(stringf("write_json %s", help_mode ? "<file-name>" : json_file.c_str()));
		}
	}
} SynthXc2064Pass;

PRIVATE_NAMESPACE_END
