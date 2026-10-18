// Four-digit BCD counter with a multiplexed 7-segment display, a design close to all 64 CLBs: a prescaler
// (PRESCALE clock cycles) advances the counter while en is high; the display moves to the next digit on every clock
// cycle (an, active low) and shows its value (seg = gfedcba, active low), both registered. Synchronous reset rst.
// PRESCALE 16 occupies 54 CLBs (routes quickly in all runs of the regression test), 10 58 CLBs, 50 61 CLBs
// (then router2 runs into the timeout in some runs, see docs/examples.md).
module bcd7seg #(
	parameter PRESCALE = 16
) (
	input            clk,
	input            rst,
	input            en,
	output reg [6:0] seg,
	output reg [3:0] an
);
	localparam W = $clog2(PRESCALE);
	reg [W-1:0] pre;
	reg [3:0]   d0, d1, d2, d3; // digits, d0 the least significant
	reg [1:0]   sel;            // digit being displayed
	wire tick = en && pre == PRESCALE - 1;

	always @(posedge clk)
		if (rst) begin
			pre <= 0;
			{d3, d2, d1, d0} <= 16'd0;
		end else begin
			if (en)
				pre <= tick ? 0 : pre + 1'b1;
			if (tick) begin
				d0 <= d0 == 9 ? 4'd0 : d0 + 1'b1;
				if (d0 == 9) begin
					d1 <= d1 == 9 ? 4'd0 : d1 + 1'b1;
					if (d1 == 9) begin
						d2 <= d2 == 9 ? 4'd0 : d2 + 1'b1;
						if (d2 == 9)
							d3 <= d3 == 9 ? 4'd0 : d3 + 1'b1;
					end
				end
			end
		end

	// Display: digit sel, its value through the decoder; at the pins from the next clock cycle on
	reg [3:0] digit;
	always @*
		case (sel)
			2'd0: digit = d0;
			2'd1: digit = d1;
			2'd2: digit = d2;
			default: digit = d3;
		endcase
	reg [6:0] s;
	always @*
		case (digit)
			4'd0: s = 7'b0111111;
			4'd1: s = 7'b0000110;
			4'd2: s = 7'b1011011;
			4'd3: s = 7'b1001111;
			4'd4: s = 7'b1100110;
			4'd5: s = 7'b1101101;
			4'd6: s = 7'b1111101;
			4'd7: s = 7'b0000111;
			4'd8: s = 7'b1111111;
			4'd9: s = 7'b1101111;
			default: s = 7'b1000000; // dash
		endcase
	always @(posedge clk) begin
		sel <= sel + 1'b1;
		seg <= ~s;
		an <= ~(4'b0001 << sel);
	end
endmodule
