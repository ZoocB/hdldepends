-- A stale file under rtl/_old/ that the config globs in then EXCLUDES with `!`.
-- It must never appear in the compile order.
library ieee;
use ieee.std_logic_1164.all;

entity legacy is
end entity;

architecture rtl of legacy is
begin
end architecture;
