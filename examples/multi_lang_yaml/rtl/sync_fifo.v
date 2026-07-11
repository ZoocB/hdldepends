// Verilog module that instantiates the SystemVerilog `fifo` module.
module sync_fifo (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] din,
    output wire [7:0] dout
);
  fifo #(.WIDTH(8), .DEPTH(32)) u_fifo (
    .clk  (clk),
    .rst  (rst),
    .din  (din),
    .dout (dout)
  );
endmodule
