// Primitive des XC2064-Modells (Simulationsmodelle; yosys liest sie mit -lib als Blackboxen).
// Präfix XC2000_ für die Familie (wie CC_ bei GateMate), damit sie sich nicht mit Zellen anderer
// Bibliotheken verwechseln lassen.
// Port- und Parameternamen müssen zu den Bel-Pins in nextpnr/xc2064_arch_gen.py passen.

// Funktionsgenerator F oder G: Funktion von 3 Variablen
module XC2000_LUT3 #(
	parameter [7:0] INIT = 8'h00
) (
	input  [2:0] I,
	output       O
);
	assign O = INIT[I];
endmodule

// F und G gemeinsam: Funktion von 4 Variablen (I[3] wählt zwischen G = INIT[15:8] und F = INIT[7:0])
module XC2000_LUT4 #(
	parameter [15:0] INIT = 16'h0000
) (
	input  [3:0] I,
	output       O
);
	assign O = INIT[I];
endmodule

// Das Speicherelement der CLB: Flipflop (LATCH=0) oder Latch (LATCH=1), Takt invertierbar (CLKINV),
// asynchrones Set S und Reset R (Reset hat Vorrang, angenommen). Nach dem Laden der Konfiguration 0.
// Im Chip kommt CLK aus K, C oder G, S aus A oder F, R aus D oder G (siehe nextpnr/xc2064.cc).
module XC2000_DFF #(
	parameter LATCH = 0,
	parameter CLKINV = 0
) (
	input      CLK,
	input      D,
	input      S,
	input      R,
	output reg Q
);
	wire c = CLK ^ CLKINV[0];
	initial Q = 1'b0;
	generate
		if (LATCH) begin
			always @*
				if (R) Q = 1'b0;
				else if (S) Q = 1'b1;
				else if (c) Q = D;
		end else begin
			always @(posedge c or posedge S or posedge R)
				if (R) Q <= 1'b0;
				else if (S) Q <= 1'b1;
				else Q <= D;
		end
	endgenerate
endmodule

module XC2000_INBUF (
	input  PAD,
	output O
);
	assign O = PAD;
endmodule

module XC2000_OUTBUF (
	input  I,
	output PAD
);
	assign PAD = I;
endmodule
