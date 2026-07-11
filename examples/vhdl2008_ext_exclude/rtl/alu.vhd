library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.pkg_types.all;

entity alu is
  port (
    a : in  std_logic_vector(WIDTH - 1 downto 0);
    b : in  std_logic_vector(WIDTH - 1 downto 0);
    y : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity;

architecture rtl of alu is
begin
  y <= std_logic_vector(unsigned(a) + unsigned(b));
end architecture;
