// Primitives of the XC2064 model (simulation models; yosys reads them with -lib as blackboxes).
// Prefix XC2000_ for the family (like CC_ for GateMate), so that they cannot be confused with cells of other
// libraries.
// Port and parameter names must match the Bel pins in nextpnr/xc2064_arch_gen.py.

// Function generator F or G: function of 3 variables
module XC2000_LUT3 #(
	parameter [7:0] INIT = 8'h00
) (
	input  [2:0] I,
	output       O
);
	assign O = INIT[I];
endmodule

// F and G together: function of 4 variables (I[3] = B selects between F = INIT[15:8] and G = INIT[7:0])
module XC2000_LUT4 #(
	parameter [15:0] INIT = 16'h0000
) (
	input  [3:0] I,
	output       O
);
	assign O = INIT[I];
endmodule

// Mux mode FGM: F and G with their own inputs, S (= B) selects between F (S = 1) and G (S = 0). Only worthwhile
// with the feedback Q: F then reads D, G its own Q (or vice versa), a function of 5 variables.
module XC2000_FGM #(
	parameter [7:0] INIT_F = 8'h00,
	parameter [7:0] INIT_G = 8'h00
) (
	input  [2:0] F,
	input  [2:0] G,
	input        S,
	output       O
);
	assign O = S ? INIT_F[F] : INIT_G[G];
endmodule

// The storage element of the CLB: flip-flop (LATCH=0) or latch (LATCH=1), clock invertible (CLKINV),
// asynchronous set S and reset R (reset has priority, assumed). 0 after loading the configuration.
// In the chip CLK comes from K, C or G, S from A or F, R from D or G (see nextpnr/xc2064.cc).
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

// IO buffers: all of them sit on an IOB. Two configuration cells switch the output driver on
// (XC2000_OUTBUF), off (XC2000_INBUF) or under the control of T (XC2000_TOBUF, XC2000_IOBUF).
// T = 1 switches the driver off, the pin is then high-impedance (datasheet, section I/O Block).
module XC2000_INBUF (
	input  PAD,
	output O
);
	assign O = PAD;
endmodule

// Latched input (XACT: I:Q, Data Book: "registered input"): an edge-triggered D FF between pad and
// input, clock K with rising edge (Data Book p. 2-214: setup and hold at the rising edge of L).
// K comes from the clock line of the chip side, all IOBs of one side share it. Cleared during configuration
// (and by RESET, not modelled), no set/reset, no clock inversion.
module XC2000_INFF (
	input      PAD,
	input      K,
	output reg O
);
	initial O = 1'b0;
	always @(posedge K)
		O <= PAD;
endmodule

module XC2000_OUTBUF (
	input  I,
	output PAD
);
	assign PAD = I;
endmodule

module XC2000_TOBUF (
	input  I,
	input  T,
	output PAD
);
	assign PAD = T ? 1'bz : I;
endmodule

module XC2000_IOBUF (
	input  I,
	input  T,
	output O,
	inout  PAD
);
	assign PAD = T ? 1'bz : I;
	assign O = PAD;
endmodule
