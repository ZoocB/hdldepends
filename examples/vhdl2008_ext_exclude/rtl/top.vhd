library ieee;
use ieee.std_logic_1164.all;

entity top is
  port (
    clk : in  std_logic;
    a   : in  std_logic_vector(15 downto 0);
    b   : in  std_logic_vector(15 downto 0);
    y   : out std_logic_vector(15 downto 0)
  );
end entity;

architecture rtl of top is
begin
  i_core : entity work.core
    port map (clk => clk, a => a, b => b, y => y);
end architecture;
