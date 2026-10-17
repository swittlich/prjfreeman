// Eingänge über das FF im IOB (gelatchter Eingang, XACT: I:Q): d wird mit clk in die IOBs übernommen, dahinter
// eine zweite Stufe in den CLBs und ein Flankendetektor. Alle IOBs einer Chipseite teilen sich einen Takt; mit
// inreg.pcf liegt d[1:0] oben und d[3:2] links, clk kommt also über zwei K-Muxe.
// erwartet: XC2000_INFF 4
module inreg (
	input        clk,
	input  [3:0] d,
	output [3:0] q,
	output [3:0] rise
);
	reg [3:0] s1, s2;
	always @(posedge clk) begin
		s1 <= d;  // im IOB
		s2 <= s1; // in den CLBs
	end
	assign q = s2;
	assign rise = s1 & ~s2;
endmodule
