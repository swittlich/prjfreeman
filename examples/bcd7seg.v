// Vierstelliger BCD-Zähler mit gemultiplexter 7-Segment-Anzeige, ein Design nahe an allen 64 CLBs: ein Vorteiler
// (PRESCALE Takte) schaltet den Zähler weiter, solange en ist; die Anzeige wechselt mit jedem Takt die Stelle
// (an, low-aktiv) und zeigt deren Ziffer (seg = gfedcba, low-aktiv), beides registriert. Synchrones Reset rst.
// PRESCALE 16 belegt 54 CLBs (routet in allen Läufen des Regressionstests schnell), 10 58 CLBs, 50 61 CLBs
// (dann läuft router2 in einigen Läufen in den Timeout, siehe README).
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
	reg [3:0]   d0, d1, d2, d3; // Ziffern, d0 die niedrigste
	reg [1:0]   sel;            // angezeigte Stelle
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

	// Anzeige: Stelle sel, Ziffer über den Decoder; ab dem nächsten Takt an den Pins
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
			default: s = 7'b1000000; // Strich
		endcase
	always @(posedge clk) begin
		sel <= sel + 1'b1;
		seg <= ~s;
		an <= ~(4'b0001 << sel);
	end
endmodule
