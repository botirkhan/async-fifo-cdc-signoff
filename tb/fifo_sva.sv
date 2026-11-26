`timescale 1ps/1ps
// Simulation assertions for async_fifo. Instantiated by tb_fifo with
// hierarchical connections to the DUT's internal pointers.
// Failures are counted (not $error) so the regression can report which
// assertions fired and keep running.
module fifo_sva #(
  parameter PW = 5
) (
  input logic          wclk,
  input logic          rclk,
  input logic          wrst_n,
  input logic          rrst_n,
  input logic [PW-1:0] wgray,
  input logic [PW-1:0] rgray,
  input logic          wr_fire,
  input logic          rd_fire,
  input logic          wr_full,
  input logic          rd_empty
);
  int unsigned fail [1:6];
  initial for (int i = 1; i <= 6; i++) fail[i] = 0;

  // A1: the write Gray pointer changes at most one bit per wclk edge
  A1_WGRAY_ONEHOT0: assert property (@(posedge wclk) disable iff (!wrst_n)
      $onehot0(wgray ^ $past(wgray)))
    else begin fail[1]++; if (fail[1] <= 3) $display("FIFO_SVA_FAIL A1_WGRAY_ONEHOT0 t=%0t", $time); end

  // A2: the read Gray pointer changes at most one bit per rclk edge
  A2_RGRAY_ONEHOT0: assert property (@(posedge rclk) disable iff (!rrst_n)
      $onehot0(rgray ^ $past(rgray)))
    else begin fail[2]++; if (fail[2] <= 3) $display("FIFO_SVA_FAIL A2_RGRAY_ONEHOT0 t=%0t", $time); end

  // A3: no write is accepted while full
  A3_NO_WRITE_WHEN_FULL: assert property (@(posedge wclk) disable iff (!wrst_n)
      wr_fire |-> !wr_full)
    else begin fail[3]++; if (fail[3] <= 3) $display("FIFO_SVA_FAIL A3_NO_WRITE_WHEN_FULL t=%0t", $time); end

  // A4: no read is accepted while empty
  A4_NO_READ_WHEN_EMPTY: assert property (@(posedge rclk) disable iff (!rrst_n)
      rd_fire |-> !rd_empty)
    else begin fail[4]++; if (fail[4] <= 3) $display("FIFO_SVA_FAIL A4_NO_READ_WHEN_EMPTY t=%0t", $time); end

  // A5: the write pointer only moves on an accepted write
  A5_WPTR_STABLE: assert property (@(posedge wclk) disable iff (!wrst_n)
      !wr_fire |=> $stable(wgray))
    else begin fail[5]++; if (fail[5] <= 3) $display("FIFO_SVA_FAIL A5_WPTR_STABLE t=%0t", $time); end

  // A6: the read pointer only moves on an accepted read
  A6_RPTR_STABLE: assert property (@(posedge rclk) disable iff (!rrst_n)
      !rd_fire |=> $stable(rgray))
    else begin fail[6]++; if (fail[6] <= 3) $display("FIFO_SVA_FAIL A6_RPTR_STABLE t=%0t", $time); end

endmodule
