// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Sebastian Wittlich
// Inputs through the FF in the IOB (latched input, XACT: I:Q): d is clocked into the IOBs by clk, followed by
// a second stage in the CLBs and an edge detector. All IOBs on one side of the chip share a clock; with
// inreg.pcf, d[1:0] is at the top and d[3:2] on the left, so clk arrives through two K muxes.
// expected: XC2000_INFF 4
module inreg (
	input        clk,
	input  [3:0] d,
	output [3:0] q,
	output [3:0] rise
);
	reg [3:0] s1, s2;
	always @(posedge clk) begin
		s1 <= d;  // in the IOB
		s2 <= s1; // in the CLBs
	end
	assign q = s2;
	assign rise = s1 & ~s2;
endmodule
