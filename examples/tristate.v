// Tristate and inout for the XC2064 model: a 4-bit bus with direction switching and a single
// tristate output. Pins in tristate.pcf.
// The enables are active low like T in the IOB (T = 1 turns the output driver off, datasheet). That way
// oe_n goes without logic from the pad over the Long Line of the edge channel to all T inputs. An active-high
// enable would need an inverter in a CLB, and its output would reach the T inputs only over the 4 tracks per channel.
module top (
	input        clk,
	input        oe_n,  // 0: the FPGA drives the bus with the counter value
	input        en_n,  // 0: tout drives the top counter bit
	inout  [3:0] bus,
	output       tout,
	output [3:0] seen   // read from the bus on every clock cycle
);
	reg [3:0] ctr, last;
	always @(posedge clk) begin
		ctr  <= ctr + 1'b1;
		last <= bus;
	end
	assign bus  = oe_n ? 4'bz : ctr;
	assign tout = en_n ? 1'bz : ctr[3];
	assign seen = last;
endmodule
