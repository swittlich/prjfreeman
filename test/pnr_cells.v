// Simulationsmodelle der Zellen, die erst nextpnr anlegt (Konstanten aus pack(), replace_constants)
module GND_DRV (output GND);
	assign GND = 1'b0;
endmodule

module VCC_DRV (output VCC);
	assign VCC = 1'b1;
endmodule
