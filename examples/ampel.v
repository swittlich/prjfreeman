// SPDX-License-Identifier: ISC
// Copyright (C) 2026 Sebastian Wittlich
// State machine: pedestrian traffic light. The cars have green until req (push button) arrives and green has lasted
// at least T_GREEN clock cycles; then yellow (T_YELLOW), red with green for the pedestrians (T_RED, walk), red-yellow
// (T_YELLOW) and green again. A shared counter times the phases, waiting remembers the request. Synchronous reset rst.
module ampel #(
	parameter T_GREEN  = 40,
	parameter T_YELLOW = 8,
	parameter T_RED    = 30
) (
	input      clk,
	input      rst,
	input      req,
	output     red,
	output     yellow,
	output     green,
	output     walk,
	output reg waiting
);
	localparam GREEN = 2'd0, YELLOW = 2'd1, RED = 2'd2, REDYELLOW = 2'd3;
	reg [1:0] state;
	reg [5:0] timer;
	wire done = timer == 0;

	always @(posedge clk)
		if (rst) begin
			state <= GREEN;
			timer <= T_GREEN - 1;
			waiting <= 1'b0;
		end else begin
			if (req)
				waiting <= 1'b1;
			if (!done)
				timer <= timer - 1'b1;
			else
				case (state)
					GREEN:
						if (waiting || req) begin
							state <= YELLOW;
							timer <= T_YELLOW - 1;
						end
					YELLOW: begin
						state <= RED;
						timer <= T_RED - 1;
						waiting <= 1'b0;
					end
					RED: begin
						state <= REDYELLOW;
						timer <= T_YELLOW - 1;
					end
					default: begin
						state <= GREEN;
						timer <= T_GREEN - 1;
					end
				endcase
		end

	assign green = state == GREEN;
	assign yellow = state == YELLOW || state == REDYELLOW;
	assign red = state == RED || state == REDYELLOW;
	assign walk = state == RED;
endmodule
