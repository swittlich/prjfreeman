// 8-bit shift register with parallel load and enable: load loads din, otherwise en shifts sin into q[0] and
// q[i-1] into q[i]; without en it holds. Each bit is a function of 5 signals (load, din[i], en, q[i-1]
// and its own q[i]): load ? din[i] : (en ? q[i-1] : q[i]). That fits into the mux mode FGM of a CLB
// (B = load selects, F reads din[i] on D, G the feedback q[i]); otherwise a bit needs two CLBs.
// expected: XC2000_FGM 8
// expected: XC2000_DFF 8
module shiftreg (
	input        clk,
	input        load,
	input        en,
	input        sin,
	input  [7:0] din,
	output [7:0] q
);
	reg [7:0] r;
	always @(posedge clk)
		if (load)
			r <= din;
		else if (en)
			r <= {r[6:0], sin};
	assign q = r;
endmodule
