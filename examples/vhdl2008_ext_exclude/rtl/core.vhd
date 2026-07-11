library ieee;
use ieee.std_logic_1164.all;

-- Mixes languages: instantiates the SystemVerilog clk_div and the VHDL alu.
entity core is
  port (
    clk : in  std_logic;
    a   : in  std_logic_vector(15 downto 0);
    b   : in  std_logic_vector(15 downto 0);
    y   : out std_logic_vector(15 downto 0)
  );
end entity;

architecture rtl of core is
  signal dclk : std_logic;
begin
  i_clk : entity work.clk_div
    port map (clk_in => clk, clk_out => dclk);

  i_alu : entity work.alu
    port map (a => a, b => b, y => y);
end architecture;
