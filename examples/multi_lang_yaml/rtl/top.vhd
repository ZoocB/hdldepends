library ieee;
use ieee.std_logic_1164.all;

entity top is
  port (
    clk : in  std_logic;
    rst : in  std_logic;
    a   : in  std_logic_vector(7 downto 0);
    b   : in  std_logic_vector(7 downto 0);
    q   : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of top is
begin
  i_dp : entity work.datapath
    port map (
      clk => clk,
      rst => rst,
      a   => a,
      b   => b,
      q   => q
    );
end architecture;
