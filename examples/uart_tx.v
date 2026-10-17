// UART-Sender 8N1: start übernimmt data und sendet Startbit, 8 Datenbits (LSB zuerst) und Stoppbit; ein Bit
// dauert CLKS_PER_BIT Takte (Standard 434: 115200 Baud bei 50 MHz, beim XC2064 eher 9600 Baud bei 4,17 MHz).
// busy ist 1, solange gesendet wird. Synchrones Reset rst.
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
	reg [W-1:0] div;  // Takte im laufenden Bit
	reg [3:0]   bitn; // 0: Startbit, 1-8: Datenbits, 9: Stoppbit
	reg [7:0]   sh;   // noch zu sendende Datenbits
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
				tx <= 1'b0; // Startbit
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
				tx <= bitn == 8 ? 1'b1 : sh[0]; // Datenbit bzw. Stoppbit
				sh <= {1'b0, sh[7:1]};
			end
		end
endmodule
