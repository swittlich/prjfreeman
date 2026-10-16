// Tristate und inout für das XC2064-Modell: ein 4-Bit-Bus mit Richtungsumschaltung und ein einzelner
// Tristate-Ausgang. Pins in tristate.pcf.
// Die Enables sind Low-aktiv wie T im IOB (T = 1 schaltet den Ausgangstreiber ab, Datenblatt). So geht
// oe_n ohne Logik vom Pad über die Long Line des Randkanals an alle T-Eingänge. Ein High-aktives Enable
// bräuchte einen Inverter in einer CLB, und dessen Ausgang käme nur über die 4 Spuren je Kanal zu den T.
module top (
	input        clk,
	input        oe_n,  // 0: das FPGA treibt den Bus mit dem Zählerstand
	input        en_n,  // 0: tout treibt das oberste Zählerbit
	inout  [3:0] bus,
	output       tout,
	output [3:0] seen   // mit jedem Takt vom Bus gelesen
);
	reg [3:0] ctr, last;
	always @(posedge clk) begin
		ctr  <= ctr + 1'b1;
		last <= bus;
	end
	assign bus  = oe_n ? 4'bz : ctr;
	assign tout = en_n ? 1'bz : ctr[3];
	assign seen = last;
endmodule
