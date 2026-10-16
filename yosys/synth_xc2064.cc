/*
 * synth_xc2064 – Yosys-Synthese für das XC2064-Modell (als Plugin).
 *
 * Erzeugt die Zellen, die die nextpnr-Himbächel-uarch "xc2064" erwartet:
 *   XC2000_LUT3   (I[2:0] -> O, INIT[7:0])   Funktionsgenerator F oder G
 *   XC2000_LUT4   (I[3:0] -> O, INIT[15:0])  F und G gemeinsam (Funktion von 4 Variablen)
 *   XC2000_DFF    (CLK, D, S, R -> Q)        das Speicherelement der CLB (FF oder Latch, Parameter
 *                                            LATCH, CLKINV), Daten nur aus F/FG, asynchrones Set/Reset
 *   XC2000_INBUF  (PAD -> O), XC2000_OUTBUF (I -> PAD)
 *   XC2000_TOBUF  (I, T -> PAD), XC2000_IOBUF (I, T -> PAD -> O)   Tristate, T = 1 schaltet ab
 * Präfix XC2000_ für die Familie (wie CC_ bei GateMate).
 *
 * Zusätzlich der Pass xc2064_ffbuf: gibt jedem FF einen eigenen treibenden LUT.
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
		log("XC2000_LUT3/XC2000_LUT4.\n");
		log("\n");
	}

	void execute(std::vector<std::string> args, RTLIL::Design *design) override
	{
		log_header(design, "Executing XC2064_FFBUF pass.\n");
		extra_args(args, 1, design);

		// Eigene Zelltypen stehen nicht in yosys' kernel/constids.inc (ID(...) geht nur dafür),
		// sondern werden im TwinePool des Designs angelegt.
		TwinePool &tw = design->twines();
		const IdString lut3 = tw.add("\\XC2000_LUT3"), lut4 = tw.add("\\XC2000_LUT4");
		const IdString dff = tw.add("\\XC2000_DFF");

		int inserted = 0;
		for (auto module : design->selected_modules()) {
			SigMap sigmap(module);
			dict<SigBit, Cell *> lut_driver;
			for (auto cell : module->cells())
				if (cell->type.in(lut3, lut4))
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
		log("function generators F/G, which can be combined into one 4-input function, and one\n");
		log("flip-flop fed from F).\n");
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
	bool noiopad;

	void clear_flags() override
	{
		top_opt = "-auto-top";
		json_file = "";
		noiopad = false;
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
			run("synth -run coarse:fine");
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
