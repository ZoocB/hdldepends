library ieee;
use ieee.std_logic_1164.all;

-- VHDL in the `work` library that mixes languages and libraries:
--   * instantiates common_lib.adder  (VHDL, another library)
--   * instantiates work.sync_fifo     (Verilog, same library, cross-language)
entity datapath is
  port (
    clk : in  std_logic;
    rst : in  std_logic;
    a   : in  std_logic_vector(7 downto 0);
    b   : in  std_logic_vector(7 downto 0);
    q   : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of datapath is
  signal sum : std_logic_vector(7 downto 0);
begin

  i_adder : entity common_lib.adder
    port map (
      a => a,
      b => b,
      y => sum
    );

  i_fifo : entity work.sync_fifo
    port map (
      clk  => clk,
      rst  => rst,
      din  => sum,
      dout => q
    );

end architecture;
