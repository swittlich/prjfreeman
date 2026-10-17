// Simulationsmodelle der Konstanten-Zellen, die nextpnr bis Stufe 3 anlegte (replace_constants). Seit
// Stufe 4 faltet pack() Konstanten in LUTs; die Modelle bleiben für ältere *.pnr.json.
module GND_DRV (output GND);
	assign GND = 1'b0;
endmodule

module VCC_DRV (output VCC);
	assign VCC = 1'b1;
endmodule
