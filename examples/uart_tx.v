// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Sebastian Wittlich
// UART transmitter 8N1: start latches data and sends a start bit, 8 data bits (LSB first) and a stop bit; one bit
// lasts CLKS_PER_BIT clock cycles (default 434: 115200 baud at 50 MHz; on the XC2064 rather 9600 baud at 4.17 MHz).
// busy is 1 while transmitting. Synchronous reset rst.
module uart_tx #(
	parameter CLKS_PER_BIT = 434
) (
	input            clk,
	input            rst,
	input            start,
	input      [7:0] data,
	output reg       tx,
	output           busy
);
	localparam W = $clog2(CLKS_PER_BIT);
	reg [W-1:0] div;  // clock cycles in the current bit
	reg [3:0]   bitn; // 0: start bit, 1-8: data bits, 9: stop bit
	reg [7:0]   sh;   // data bits still to be sent
	reg         run;
	assign busy = run;

	always @(posedge clk)
		if (rst) begin
			run <= 1'b0;
			tx <= 1'b1;
			div <= 0;
			bitn <= 0;
		end else if (!run) begin
			tx <= 1'b1;
			if (start) begin
				run <= 1'b1;
				sh <= data;
				bitn <= 0;
				div <= 0;
				tx <= 1'b0; // start bit
			end
		end else if (div != CLKS_PER_BIT - 1) begin
			div <= div + 1'b1;
		end else begin
			div <= 0;
			if (bitn == 9) begin
				run <= 1'b0;
				tx <= 1'b1;
			end else begin
				bitn <= bitn + 1'b1;
				tx <= bitn == 8 ? 1'b1 : sh[0]; // data bit or stop bit
				sh <= {1'b0, sh[7:1]};
			end
		end
endmodule
