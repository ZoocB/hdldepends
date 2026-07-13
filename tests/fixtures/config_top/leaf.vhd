library ieee;
use ieee.std_logic_1164.all;

entity leaf is
  port (
    a_i : in  std_logic;
    b_o : out std_logic
  );
end entity;

architecture rtl of leaf is
begin
  b_o <= a_i;
end architecture;
