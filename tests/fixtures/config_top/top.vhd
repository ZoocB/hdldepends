library ieee;
use ieee.std_logic_1164.all;

entity top is
  port (
    a_i : in  std_logic;
    b_o : out std_logic
  );
end entity;

architecture rtl of top is
begin

  i_leaf : entity work.leaf
  port map (
    a_i => a_i,
    b_o => b_o
  );

end architecture;
