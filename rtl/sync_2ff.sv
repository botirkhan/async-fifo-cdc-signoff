`timescale 1ps/1ps
// Two-flop synchronizer for a Gray-coded bus.
//
// META_INJECT (simulation / formal only): models metastability in the first
// stage. Any bit that changed since the previous destination edge may resolve
// to its old value (d_old = the source register's value before its latest
// change). For a Gray bus that only ever gives the old or the new pointer; for
// a binary bus it can give a value that never existed, which is the failure a
// CDC review is meant to prevent.
module sync_2ff #(
  parameter W = 1
) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic [W-1:0] d,
`ifdef META_INJECT
  input  logic [W-1:0] d_old,
`endif
  output logic [W-1:0] q
);
  (* ASYNC_REG = "TRUE" *) logic [W-1:0] s1;
  (* ASYNC_REG = "TRUE" *) logic [W-1:0] s2;
  logic [W-1:0] d_cap;

`ifdef META_INJECT
  logic [W-1:0] d_last;
  logic [W-1:0] meta;
 `ifdef FORMAL
  (* anyseq *) wire [W-1:0] f_pick;     // solver chooses how each bit resolves
  assign meta = f_pick & (d ^ d_last);
 `else
  logic [31:0] rnd = 32'd0;
  always_ff @(posedge clk) rnd <= $urandom;
  assign meta = rnd[W-1:0] & (d ^ d_last);
 `endif
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) d_last <= '0;
    else        d_last <= d;
  assign d_cap = (d & ~meta) | (d_old & meta);
`else
  assign d_cap = d;
`endif

  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      s1 <= '0;
      s2 <= '0;
    end else begin
      s1 <= d_cap;
      s2 <= s1;
    end

`ifdef BUG_ONE_FLOP
  assign q = s1;           // mutant: first (possibly metastable) stage used directly
`else
  assign q = s2;
`endif
endmodule
