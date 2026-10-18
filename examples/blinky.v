// Blinky for the XC2064 model: 16-bit counter, the upper 8 bits on LEDs.
// The pins are in blinky.pcf (PLCC68 pin numbers). The clock is on P9, the pin with the global
// clock buffer GCLK -> K of all CLBs. Without an entry in the PCF file the placer decides; nextpnr then
// puts the clock on P9 by itself.
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
