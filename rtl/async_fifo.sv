`timescale 1ps/1ps
// Parameterized dual-clock (asynchronous) FIFO.
//
// * Each side keeps a binary pointer (addresses the RAM) and a Gray copy
//   (the only thing that crosses to the other clock domain).
// * Pointers are ADDR_W+1 bits; the extra MSB tells "full" from "empty".
// * Each Gray pointer goes through a 2-flop synchronizer (sync_2ff).
// * full  : next write Gray pointer == synchronized read pointer with its
//           two MSBs inverted.
// * empty : next read Gray pointer == synchronized write pointer.
// * rdata is first-word-fall-through: it shows the head entry while !rd_empty.
//
// Injected bugs for mutation testing (compile with +define+BUG_x):
//   BUG_WR_WHEN_FULL   write enable not gated by full (overwrites unread data)
//   BUG_RD_WHEN_EMPTY  read enable not gated by empty (reads past the write pointer)
//   BUG_FULL_MSB       full compare inverts only the MSB (binary-style compare on Gray)
//   BUG_GRAY_CONV      wrong binary-to-Gray conversion on the write pointer
//   BUG_BIN_CROSS      binary pointers cross the clock domains instead of Gray
//   BUG_ONE_FLOP       (in sync_2ff) only one synchronizer stage
module async_fifo #(
  parameter DATA_W = 16,
  parameter ADDR_W = 4          // depth = 2**ADDR_W, ADDR_W >= 2
) (
  // write clock domain
  input  logic              wclk,
  input  logic              wrst_n,
  input  logic              wr_en,
  input  logic [DATA_W-1:0] wdata,
  output logic              wr_full,
  // read clock domain
  input  logic              rclk,
  input  logic              rrst_n,
  input  logic              rd_en,
  output logic [DATA_W-1:0] rdata,
  output logic              rd_empty
);
  localparam DEPTH = 1 << ADDR_W;
  localparam PW    = ADDR_W + 1;

  logic [DATA_W-1:0] mem [0:DEPTH-1];

  logic [PW-1:0] wbin, wgray, wbin_next, wgray_next;
  logic [PW-1:0] rbin, rgray, rbin_next, rgray_next;
  logic [PW-1:0] wq2_rgray;     // read pointer, synchronized into wclk
  logic [PW-1:0] rq2_wgray;     // write pointer, synchronized into rclk
  logic          wr_fire, rd_fire, wfull_next, rempty_next;

  // ------------------------------------------------------------ write side
`ifdef BUG_WR_WHEN_FULL
  assign wr_fire = wr_en;
`else
  assign wr_fire = wr_en && !wr_full;
`endif
  assign wbin_next = wbin + {{ADDR_W{1'b0}}, wr_fire};
`ifdef BUG_GRAY_CONV
  assign wgray_next = wbin_next ^ (wbin_next >> 2);
`else
  assign wgray_next = wbin_next ^ (wbin_next >> 1);
`endif
`ifdef BUG_FULL_MSB
  assign wfull_next = (wgray_next == {~wq2_rgray[PW-1], wq2_rgray[PW-2:0]});
`else
  assign wfull_next = (wgray_next == {~wq2_rgray[PW-1:PW-2], wq2_rgray[PW-3:0]});
`endif

  always_ff @(posedge wclk)
    if (wr_fire) mem[wbin[ADDR_W-1:0]] <= wdata;

  always_ff @(posedge wclk or negedge wrst_n)
    if (!wrst_n) begin
      wbin    <= '0;
      wgray   <= '0;
      wr_full <= 1'b0;
    end else begin
      wbin    <= wbin_next;
      wgray   <= wgray_next;
      wr_full <= wfull_next;
    end

  // ------------------------------------------------------------- read side
`ifdef BUG_RD_WHEN_EMPTY
  assign rd_fire = rd_en;
`else
  assign rd_fire = rd_en && !rd_empty;
`endif
  assign rbin_next   = rbin + {{ADDR_W{1'b0}}, rd_fire};
  assign rgray_next  = rbin_next ^ (rbin_next >> 1);
  assign rempty_next = (rgray_next == rq2_wgray);

  always_ff @(posedge rclk or negedge rrst_n)
    if (!rrst_n) begin
      rbin     <= '0;
      rgray    <= '0;
      rd_empty <= 1'b1;
    end else begin
      rbin     <= rbin_next;
      rgray    <= rgray_next;
      rd_empty <= rempty_next;
    end

  assign rdata = mem[rbin[ADDR_W-1:0]];

  // ------------------------------------------------------- clock crossings
`ifdef META_INJECT
  // value of each crossing register before its latest change (for sync_2ff)
  logic [PW-1:0] w_xold, r_xold;
 `ifdef BUG_BIN_CROSS
  always_ff @(posedge wclk or negedge wrst_n)
    if (!wrst_n) w_xold <= '0; else if (wbin_next != wbin) w_xold <= wbin;
  always_ff @(posedge rclk or negedge rrst_n)
    if (!rrst_n) r_xold <= '0; else if (rbin_next != rbin) r_xold <= rbin;
 `else
  always_ff @(posedge wclk or negedge wrst_n)
    if (!wrst_n) w_xold <= '0; else if (wgray_next != wgray) w_xold <= wgray;
  always_ff @(posedge rclk or negedge rrst_n)
    if (!rrst_n) r_xold <= '0; else if (rgray_next != rgray) r_xold <= rgray;
 `endif
`endif

`ifdef BUG_BIN_CROSS
  logic [PW-1:0] rq2_wbin, wq2_rbin;
  sync_2ff #(.W(PW)) u_w2r_sync (
    .clk(rclk), .rst_n(rrst_n), .d(wbin),
 `ifdef META_INJECT
    .d_old(w_xold),
 `endif
    .q(rq2_wbin));
  sync_2ff #(.W(PW)) u_r2w_sync (
    .clk(wclk), .rst_n(wrst_n), .d(rbin),
 `ifdef META_INJECT
    .d_old(r_xold),
 `endif
    .q(wq2_rbin));
  assign rq2_wgray = rq2_wbin ^ (rq2_wbin >> 1);
  assign wq2_rgray = wq2_rbin ^ (wq2_rbin >> 1);
`else
  sync_2ff #(.W(PW)) u_w2r_sync (
    .clk(rclk), .rst_n(rrst_n), .d(wgray),
 `ifdef META_INJECT
    .d_old(w_xold),
 `endif
    .q(rq2_wgray));
  sync_2ff #(.W(PW)) u_r2w_sync (
    .clk(wclk), .rst_n(wrst_n), .d(rgray),
 `ifdef META_INJECT
    .d_old(r_xold),
 `endif
    .q(wq2_rgray));
`endif

  // ----------------------------------------------- formal-only properties
`ifdef FORMAL
  // F_GRAY: each crossing Gray pointer changes at most one bit per edge
  logic [PW-1:0] f_wgray_q, f_rgray_q;
  always_ff @(posedge wclk or negedge wrst_n)
    if (!wrst_n) f_wgray_q <= '0; else f_wgray_q <= wgray;
  always_ff @(posedge rclk or negedge rrst_n)
    if (!rrst_n) f_rgray_q <= '0; else f_rgray_q <= rgray;
  wire [PW-1:0] f_wdiff = wgray ^ f_wgray_q;
  wire [PW-1:0] f_rdiff = rgray ^ f_rgray_q;
  always @(*) begin
    if (wrst_n) assert ((f_wdiff & (f_wdiff - 1'b1)) == '0);  // PROP F_WGRAY_ONEHOT0
    if (rrst_n) assert ((f_rdiff & (f_rdiff - 1'b1)) == '0);  // PROP F_RGRAY_ONEHOT0
  end
`endif
endmodule
