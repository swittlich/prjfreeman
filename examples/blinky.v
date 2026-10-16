// Blinky für das XC2064-Modell: 16-Bit-Zähler, die oberen 8 Bit auf LEDs.
// Der Takt kommt über Pin P9 (globaler Taktpuffer GCLK -> K aller CLBs). Pins wählt man per
// (* LOC="Pxx" *) am INBUF/OUTBUF (PLCC68-Pinnummern), ohne LOC entscheidet der Placer.
module top (
	input        clk,
	input        rst,
	output [7:0] leds
);
	wire clk_i;
	(* LOC="P9" *) INBUF clk_ibuf (.PAD(clk), .O(clk_i));

	reg [15:0] ctr;
	always @(posedge clk_i)
		if (rst)
			ctr <= 16'd0;
		else
			ctr <= ctr + 1'b1;

	assign leds = ctr[15:8];
endmodule
