// 8-Bit-Schieberegister mit parallelem Laden und Enable: load lädt din, sonst schiebt en sin nach q[0] und
// q[i-1] nach q[i], ohne en hält es. Jedes Bit ist eine Funktion von 5 Signalen (load, din[i], en, q[i-1]
// und sein eigenes q[i]): load ? din[i] : (en ? q[i-1] : q[i]). Das passt in den Mux-Modus FGM einer CLB
// (B = load wählt, F liest din[i] an D, G die Rückführung q[i]), sonst braucht ein Bit zwei CLBs.
// erwartet: XC2000_FGM 8
// erwartet: XC2000_DFF 8
module shiftreg (
	input        clk,
	input        load,
	input        en,
	input        sin,
	input  [7:0] din,
	output [7:0] q
);
	reg [7:0] r;
	always @(posedge clk)
		if (load)
			r <= din;
		else if (en)
			r <= {r[6:0], sin};
	assign q = r;
endmodule
