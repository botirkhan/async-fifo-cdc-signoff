`timescale 1ps/1ps
// Self-checking constrained-random testbench for async_fifo.
// Runs on Vivado xsim (local regression) and Verilator --timing (CI).
//
// Plusargs (all integers): WPER / RPER clock periods in ps, WPHASE / RPHASE
// start offsets in ps, NUM_TXN writes to issue, SEED.
//
// Stimulus is driven and sampled on the falling edge of each clock, so a
// "valid at negedge" request is the handshake at the next rising edge.
// Checks:
//   scoreboard  - every read returns the oldest unread write (queue model)
//   overflow    - a write accepted while the FIFO already holds DEPTH entries
//   underflow   - a read accepted while the FIFO holds nothing
//   drain       - after traffic stops every write comes out, then empty=1, full=0
//   SVA         - fifo_sva (Gray one-hot, no write when full, ...)
module tb_fifo;
  localparam int DATA_W = 16;
  localparam int ADDR_W = 4;
  localparam int DEPTH  = 1 << ADDR_W;
  localparam int NBINS  = DEPTH + 1 + 4;

  logic wclk = 1'b0, rclk = 1'b0;
  logic wrst_n = 1'b0, rrst_n = 1'b0;
  logic wr_en = 1'b0, rd_en = 1'b0;
  logic [DATA_W-1:0] wdata = '0;
  wire               wr_full, rd_empty;
  wire  [DATA_W-1:0] rdata;

  async_fifo #(.DATA_W(DATA_W), .ADDR_W(ADDR_W)) dut (
    .wclk(wclk), .wrst_n(wrst_n), .wr_en(wr_en), .wdata(wdata), .wr_full(wr_full),
    .rclk(rclk), .rrst_n(rrst_n), .rd_en(rd_en), .rdata(rdata), .rd_empty(rd_empty));

  fifo_sva #(.PW(ADDR_W + 1)) u_sva (
    .wclk(wclk), .rclk(rclk), .wrst_n(wrst_n), .rrst_n(rrst_n),
    .wgray(dut.wgray), .rgray(dut.rgray), .wr_fire(dut.wr_fire), .rd_fire(dut.rd_fire),
    .wr_full(wr_full), .rd_empty(rd_empty));

  // ---------------------------------------------------------------- config
  int unsigned wper = 10000, rper = 10000, wphase = 0, rphase = 0;
  int unsigned num_txn = 2000, seed = 1;

  // ----------------------------------------------------------------- state
  logic [DATA_W-1:0] model [$];
  int unsigned mode = 0;
  int unsigned wcyc = 0, rcyc = 0;
  int unsigned wr_issued = 0, rd_done = 0;
  int unsigned wr_cnt = 0, rd_cnt = 0;        // updated on the real rising edges
  int unsigned checks = 0, mismatches = 0, overflow = 0, underflow = 0;
  int unsigned full_cycles = 0, empty_cycles = 0;
  bit          w_acc = 1'b0, r_acc = 1'b0;
  bit          draining = 1'b0;
  bit          cov [0:NBINS-1];               // occupancy 0..DEPTH, full, re-empty, wr blocked, rd blocked

  function automatic bit chance(int unsigned pct);
    return ($urandom % 100) < pct;
  endfunction

  // traffic modes: write % / read % per clock cycle
  function automatic int unsigned wr_pct(int unsigned m);
    case (m)
      0: return 50;  1: return 90;  2: return 20;
      3: return 100; 4: return 100; default: return 0;
    endcase
  endfunction
  function automatic int unsigned rd_pct(int unsigned m);
    case (m)
      0: return 50;  1: return 20;  2: return 90;
      3: return 100; 4: return 0;   default: return 100;
    endcase
  endfunction

  function automatic int unsigned sva_total();
    int unsigned t = 0;
    for (int i = 1; i <= 6; i++) t += u_sva.fail[i];
    return t;
  endfunction

  task automatic mark_occ();
    int unsigned occ;
    occ = wr_cnt - rd_cnt;
    if (occ <= DEPTH) cov[occ] = 1'b1;
  endtask

  // ------------------------------------------------------------ write side
  always @(negedge wclk) begin
    if (wrst_n) begin
      wcyc++;
      if (wcyc % 128 == 0) mode = $urandom % 6;
      wr_en = (wr_issued < num_txn) && chance(wr_pct(mode));
      wdata = DATA_W'($urandom);
      w_acc = wr_en && !wr_full;
      if (wr_full) full_cycles++;
      if (wr_full) cov[DEPTH + 1] = 1'b1;
      if (wr_en && wr_full) cov[DEPTH + 3] = 1'b1;
      if (w_acc) begin
        model.push_back(wdata);
        wr_issued++;
      end
    end
  end

  always @(posedge wclk) begin
    if (wrst_n && w_acc) begin
      if (wr_cnt - rd_cnt >= DEPTH) begin
        overflow++;
        if (overflow <= 3) $display("FIFO_OVERFLOW t=%0t write accepted with %0d entries stored", $time, wr_cnt - rd_cnt);
      end
      wr_cnt++;
      mark_occ();
    end
  end

  // ------------------------------------------------------------- read side
  always @(negedge rclk) begin
    logic [DATA_W-1:0] exp;
    if (rrst_n) begin
      rcyc++;
      rd_en = draining ? 1'b1 : chance(rd_pct(mode));
      r_acc = rd_en && !rd_empty;
      if (rd_empty) empty_cycles++;
      if (rd_empty && rd_done > 0) cov[DEPTH + 2] = 1'b1;
      if (rd_en && rd_empty) cov[DEPTH + 4] = 1'b1;
      if (r_acc) begin
        checks++;
        if (model.size() == 0) begin
          mismatches++;
          if (mismatches <= 5) $display("FIFO_MISMATCH t=%0t read with empty model, rdata=%h", $time, rdata);
        end else begin
          exp = model.pop_front();
          if (rdata !== exp) begin
            mismatches++;
            if (mismatches <= 5) $display("FIFO_MISMATCH t=%0t read #%0d got %h expected %h", $time, rd_done, rdata, exp);
          end
        end
        rd_done++;
      end
    end
  end

  always @(posedge rclk) begin
    if (rrst_n && r_acc) begin
      if (wr_cnt == rd_cnt) begin
        underflow++;
        if (underflow <= 3) $display("FIFO_UNDERFLOW t=%0t read accepted with 0 entries stored", $time);
      end
      rd_cnt++;
      mark_occ();
    end
  end

  // ------------------------------------------------------------------ main
  initial begin
    longint unsigned limit;
    int unsigned guard, hits, slow;
    bit drained, pass, got;
    got = $value$plusargs("WPER=%d", wper);
    got = $value$plusargs("RPER=%d", rper);
    got = $value$plusargs("WPHASE=%d", wphase);
    got = $value$plusargs("RPHASE=%d", rphase);
    got = $value$plusargs("NUM_TXN=%d", num_txn);
    got = $value$plusargs("SEED=%d", seed);   // RNG seed itself comes from -sv_seed / +verilator+seed
    for (int i = 0; i < NBINS; i++) cov[i] = 1'b0;
    slow = (wper > rper) ? wper : rper;

    fork
      begin
        #(wphase);
        forever #(wper / 2) wclk = ~wclk;
      end
      begin
        #(rphase);
        forever #(rper / 2) rclk = ~rclk;
      end
      begin
        limit = longint'(num_txn) * longint'(slow) * 64 + 64'd100000000;
        #(limit);
        $display("FIFO_RESULT pass=0 timeout=1 writes=%0d reads=%0d checks=%0d mismatches=%0d overflow=%0d underflow=%0d sva_fail=%0d",
                 wr_issued, rd_done, checks, mismatches, overflow, underflow, sva_total());
        $finish;
      end
    join_none

    // resets: asserted at time 0, released on each clock's falling edge
    repeat (4) @(posedge wclk);
    repeat (4) @(posedge rclk);
    @(negedge wclk) wrst_n = 1'b1;
    @(negedge rclk) rrst_n = 1'b1;

    // traffic runs in the always blocks until every write is issued
    while (wr_issued < num_txn) @(posedge wclk);
    draining = 1'b1;
    guard = 0;
    while (rd_done < wr_issued && guard < DEPTH * 64 + 1000) begin
      @(posedge rclk);
      guard++;
    end
    // let the last pointers synchronize, keep reading (must not underflow)
    repeat (8) @(posedge wclk);
    repeat (8) @(posedge rclk);
    @(negedge rclk);

    drained = (rd_done == wr_issued) && (model.size() == 0) && rd_empty && !wr_full;
    hits = 0;
    for (int i = 0; i < NBINS; i++) hits += cov[i];
    pass = (mismatches == 0) && (overflow == 0) && (underflow == 0) &&
           (sva_total() == 0) && drained;

    $display("FIFO_RESULT pass=%0d timeout=0 writes=%0d reads=%0d checks=%0d mismatches=%0d overflow=%0d underflow=%0d sva_fail=%0d drained=%0d cov_hit=%0d cov_bins=%0d full_cycles=%0d empty_cycles=%0d wcycles=%0d rcycles=%0d",
             pass, wr_issued, rd_done, checks, mismatches, overflow, underflow, sva_total(),
             drained, hits, NBINS, full_cycles, empty_cycles, wcyc, rcyc);
    $display("FIFO_SVA A1:%0d A2:%0d A3:%0d A4:%0d A5:%0d A6:%0d",
             u_sva.fail[1], u_sva.fail[2], u_sva.fail[3], u_sva.fail[4], u_sva.fail[5], u_sva.fail[6]);
    $finish;
  end
endmodule
