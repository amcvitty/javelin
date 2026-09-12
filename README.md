# Repository Coverage



| Name                               |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| analytics/\_\_init\_\_.py          |        5 |        0 |        0 |        0 |    100% |           |
| analytics/blackscholes.py          |       16 |        0 |        0 |        0 |    100% |           |
| analytics/book.py                  |       22 |        3 |        0 |        0 |     86% |25, 34, 57 |
| analytics/instrument.py            |       47 |        2 |        0 |        0 |     96% |    48, 58 |
| analytics/market.py                |       22 |        1 |        0 |        0 |     95% |        44 |
| graph/\_\_init\_\_.py              |       26 |        0 |        0 |        0 |    100% |           |
| graph/cell.py                      |       74 |        1 |       10 |        1 |     98% |       212 |
| graph/compiler.py                  |       82 |        2 |       18 |        1 |     97% |58-\>57, 110-112 |
| graph/ir.py                        |       67 |        0 |        8 |        0 |    100% |           |
| graph/node.py                      |       82 |       12 |       20 |        1 |     83% |18, 63-66, 69-71, 74, 77, 127, 130, 182 |
| graph/rewriter.py                  |      323 |       20 |      104 |       11 |     92% |88-90, 462, 508, 566, 574, 585, 596, 606, 614, 651-656, 674, 700-701, 719 |
| graph/runtime.py                   |      279 |        2 |       90 |        1 |     99% |  174, 211 |
| ns/\_\_init\_\_.py                 |       16 |        2 |        0 |        0 |     88% |    48, 58 |
| ns/mcobject.py                     |       23 |        0 |        2 |        0 |    100% |           |
| ns/namespace.py                    |       68 |        6 |       18 |        1 |     92% |36-39, 62, 119 |
| ns/store.py                        |       54 |        2 |       12 |        1 |     95% |   63, 107 |
| tui/\_\_init\_\_.py                |        0 |        0 |        0 |        0 |    100% |           |
| tui/graph\_browser/\_\_init\_\_.py |       11 |        4 |        2 |        1 |     62% |41-42, 47-49 |
| tui/graph\_browser/\_\_main\_\_.py |        2 |        2 |        0 |        0 |      0% |      8-10 |
| tui/graph\_browser/app.py          |      108 |       11 |       18 |        6 |     85% |125-126, 132, 143-146, 162, 168, 170, 178 |
| tui/graph\_browser/navigation.py   |       62 |        2 |       18 |        2 |     95% |  127, 132 |
| tui/graph\_browser/render.py       |       85 |        0 |       26 |        0 |    100% |           |
| **TOTAL**                          | **1474** |   **72** |  **346** |   **26** | **94%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://github.com/amcvitty/beacon-clone/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/amcvitty/beacon-clone/tree/python-coverage-comment-action-data)

This is the one to use if your repository is private or if you don't want to customize anything.



## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.