// SystemVerilog clock divider (work library, no VHDL standard tag).
module clk_div #(
    parameter DIV = 2
) (
    input  logic clk_in,
    output logic clk_out
);
  always_ff @(posedge clk_in) clk_out <= ~clk_out;
endmodule
