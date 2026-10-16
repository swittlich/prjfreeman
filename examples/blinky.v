// Blinky für das XC2064-Modell: 16-Bit-Zähler, die oberen 8 Bit auf LEDs.
// Die Pins stehen in blinky.pcf (PLCC68-Pinnummern). Der Takt liegt an P9, dem Pin mit dem globalen
// Taktpuffer GCLK -> K aller CLBs. Ohne Eintrag in der PCF-Datei entscheidet der Placer.
module top (
	input        clk,
	input        rst,
	output [7:0] leds
);
	reg [15:0] ctr;
	always @(posedge clk)
		if (rst)
			ctr <= 16'd0;
		else
			ctr <= ctr + 1'b1;

	assign leds = ctr[15:8];
endmodule
