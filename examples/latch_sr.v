// Test der Speicher-Varianten des XC2064-Modells: Flipflop mit fallender Flanke, asynchrones
// Set/Reset und ein transparentes Latch. Pins in latch_sr.pcf, der Takt an P9 (GCLK).
module top (
	input        clk,
	input        en,
	input        set,
	input        rst,
	input  [1:0] d,
	output [2:0] q
);
	reg q_neg, q_sr, q_lat;
	always @(negedge clk)                   // fallende Flanke -> CLKINV
		q_neg <= d[0] ^ d[1];
	always @(posedge clk or posedge set or posedge rst)  // asynchrones Set/Reset
		if (rst) q_sr <= 1'b0;
		else if (set) q_sr <= 1'b1;
		else q_sr <= d[0] & d[1];
	always @*                                // Latch
		if (en) q_lat = d[1];

	assign q = {q_lat, q_sr, q_neg};
endmodule
