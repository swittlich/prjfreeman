// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Sebastian Wittlich
// Simulation models of the constant cells that nextpnr created up to stage 3 (replace_constants). Since
// stage 4, pack() folds constants into LUTs; the models remain for older *.pnr.json.
module GND_DRV (output GND);
	assign GND = 1'b0;
endmodule

module VCC_DRV (output VCC);
	assign VCC = 1'b1;
endmodule
