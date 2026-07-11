library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Uses the package from its own library (common_lib.math_pkg).
library common_lib;
use common_lib.math_pkg.all;

entity adder is
  port (
    a : in  std_logic_vector(DATA_W - 1 downto 0);
    b : in  std_logic_vector(DATA_W - 1 downto 0);
    y : out std_logic_vector(DATA_W - 1 downto 0)
  );
end entity;

architecture rtl of adder is
begin
  y <= std_logic_vector(unsigned(a) + unsigned(b));
end architecture;
