"""Pure-Python port of GridCraft's formula engine.

Importing the package imports :mod:`activities._formula.functions`, which fills the worksheet
function registry that :mod:`activities._formula.evaluator` dispatches to.
"""

from activities._formula import functions
from activities._formula.workbook import Workbook

__all__ = ["Workbook", "functions"]
