// SystemVerilog leaf module (compiled into the default `work` library).
module fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
) (
    input  logic             clk,
    input  logic             rst,
    input  logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout
);
  logic [WIDTH-1:0] mem [0:DEPTH-1];
  always_ff @(posedge clk) begin
    dout <= din;
  end
endmodule
