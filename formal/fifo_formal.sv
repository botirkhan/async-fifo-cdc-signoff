// Formal harness for async_fifo (SymbiYosys, "multiclock on").
// wclk and rclk are free inputs, so the solver explores every clock ratio and
// phase. META_INJECT lets the solver pick how each changing synchronizer bit
// resolves. Shadow counters count accepted writes/reads at the ports, so the
// properties are written against the spec, not the DUT's own pointers.
module fifo_formal (
  input wire       wclk,
  input wire       rclk,
  input wire       wrst_n,
  input wire       rrst_n,
  input wire       wr_en,
  input wire       rd_en,
  input wire [3:0] wdata
);
  localparam DATA_W = 4;
  localparam ADDR_W = 2;
  localparam DEPTH  = 4;

  wire              wr_full, rd_empty;
  wire [DATA_W-1:0] rdata;

  async_fifo #(.DATA_W(DATA_W), .ADDR_W(ADDR_W)) dut (
    .wclk(wclk), .wrst_n(wrst_n), .wr_en(wr_en), .wdata(wdata), .wr_full(wr_full),
    .rclk(rclk), .rrst_n(rrst_n), .rd_en(rd_en), .rdata(rdata), .rd_empty(rd_empty));

  // ---- resets: both asserted at step 0, each released once, never re-asserted
  reg f_init = 1'b1;
  reg f_wrel = 1'b0;
  reg f_rrel = 1'b0;
  always @($global_clock) begin
    f_init <= 1'b0;
    if (wrst_n) f_wrel <= 1'b1;
    if (rrst_n) f_rrel <= 1'b1;
  end
  always @(*) begin
    if (f_init) assume (!wrst_n && !rrst_n);
    if (f_wrel) assume (wrst_n);
    if (f_rrel) assume (rrst_n);
  end

  // ---- shadow counters of accepted transfers (spec level)
  reg [7:0] f_wcnt, f_rcnt;
  always @(posedge wclk or negedge wrst_n)
    if (!wrst_n) f_wcnt <= 8'd0;
    else if (wr_en && !wr_full) f_wcnt <= f_wcnt + 8'd1;
  always @(posedge rclk or negedge rrst_n)
    if (!rrst_n) f_rcnt <= 8'd0;
    else if (rd_en && !rd_empty) f_rcnt <= f_rcnt + 8'd1;
  wire [7:0] f_fill = f_wcnt - f_rcnt;

  // ---- track one arbitrary write (number f_idx) through the FIFO
  (* anyconst *) reg [7:0] f_idx;
  reg              f_wrote;
  reg [DATA_W-1:0] f_data;
  always @(posedge wclk or negedge wrst_n)
    if (!wrst_n) begin
      f_wrote <= 1'b0;
      f_data  <= '0;
    end else if (wr_en && !wr_full && f_wcnt == f_idx) begin
      f_wrote <= 1'b1;
      f_data  <= wdata;
    end

  always @(*) begin
    if (wrst_n && rrst_n) begin
      assert (f_fill <= DEPTH);                                   // PROP P1_NO_OVERFLOW_UNDERFLOW
      if (!rd_empty) assert (f_fill != 8'd0);                     // PROP P2_EMPTY_SAFE
      if (!wr_full)  assert (f_fill != DEPTH);                    // PROP P3_FULL_SAFE
      if (!rd_empty && f_rcnt == f_idx)
        assert (f_wrote && rdata == f_data);                      // PROP P4_DATA_IN_ORDER
    end
  end

  // ---- covers (non-vacuity): run with "sby fifo.sby cover"
  always @(*) begin
    if (wrst_n && rrst_n) begin
      cover (f_fill == DEPTH && wr_full);                         // COVER C1_FULL
      cover (f_rcnt == 8'd5 && rd_empty);                         // COVER C2_FILL_THEN_DRAIN
      cover (f_wcnt == 8'd9);                                     // COVER C3_POINTER_WRAP
    end
  end
endmodule
