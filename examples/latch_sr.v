// Test of the storage variants of the XC2064 model: flip-flop on the falling edge, asynchronous
// set/reset and a transparent latch. Pins in latch_sr.pcf, the clock on P9 (GCLK).
module top (
	input        clk,
	input        en,
	input        set,
	input        rst,
	input  [1:0] d,
	output [2:0] q
);
	reg q_neg, q_sr, q_lat;
	always @(negedge clk)                   // falling edge -> CLKINV
		q_neg <= d[0] ^ d[1];
	always @(posedge clk or posedge set or posedge rst)  // asynchronous set/reset
		if (rst) q_sr <= 1'b0;
		else if (set) q_sr <= 1'b1;
		else q_sr <= d[0] & d[1];
	always @*                                // Latch
		if (en) q_lat = d[1];

	assign q = {q_lat, q_sr, q_neg};
endmodule
