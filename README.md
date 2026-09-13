# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/amcvitty/javelin/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                               |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| analytics/\_\_init\_\_.py          |        5 |        0 |        0 |        0 |    100% |           |
| analytics/blackscholes.py          |       16 |        0 |        0 |        0 |    100% |           |
| analytics/book.py                  |       22 |        3 |        0 |        0 |     86% |25, 34, 57 |
| analytics/instrument.py            |       47 |        2 |        0 |        0 |     96% |    48, 58 |
| analytics/market.py                |       22 |        1 |        0 |        0 |     95% |        44 |
| graph/\_\_init\_\_.py              |       34 |        0 |        2 |        0 |    100% |           |
| graph/cell.py                      |       74 |        1 |       10 |        1 |     98% |       212 |
| graph/compiler.py                  |       82 |        2 |       18 |        1 |     97% |58-\>57, 110-112 |
| graph/ir.py                        |       67 |        0 |        8 |        0 |    100% |           |
| graph/node.py                      |       82 |       12 |       20 |        1 |     83% |18, 63-66, 69-71, 74, 77, 127, 130, 182 |
| graph/rewriter.py                  |      323 |       20 |      104 |       11 |     92% |88-90, 462, 508, 566, 574, 585, 596, 606, 614, 651-656, 674, 700-701, 719 |
| graph/runtime.py                   |      279 |        2 |       90 |        1 |     99% |  174, 211 |
| ns/\_\_init\_\_.py                 |       16 |        2 |        0 |        0 |     88% |    48, 58 |
| ns/mcobject.py                     |       23 |        1 |        2 |        0 |     96% |        68 |
| ns/namespace.py                    |       68 |        6 |       18 |        1 |     92% |36-39, 62, 119 |
| ns/store.py                        |       54 |        2 |       12 |        1 |     95% |   63, 107 |
| tui/\_\_init\_\_.py                |        0 |        0 |        0 |        0 |    100% |           |
| tui/graph\_browser/\_\_init\_\_.py |       11 |        4 |        2 |        1 |     62% |41-42, 47-49 |
| tui/graph\_browser/\_\_main\_\_.py |        2 |        2 |        0 |        0 |      0% |      9-11 |
| tui/graph\_browser/app.py          |      178 |       12 |       34 |        7 |     89% |128, 223-224, 227-\>exit, 233, 249-\>251, 252-259, 290, 296, 298 |
| tui/graph\_browser/navigation.py   |       62 |        2 |       18 |        2 |     95% |  127, 132 |
| tui/graph\_browser/render.py       |      101 |        1 |       28 |        1 |     98% |       171 |
| viz/\_\_init\_\_.py                |        4 |        0 |        0 |        0 |    100% |           |
| viz/\_\_main\_\_.py                |       13 |       13 |        2 |        0 |      0% |     14-29 |
| viz/build.py                       |       96 |        0 |       26 |        1 |     99% | 169-\>166 |
| viz/render.py                      |       22 |        0 |        6 |        0 |    100% |           |
| viz/show.py                        |       40 |        1 |        2 |        0 |     98% |        45 |
| **TOTAL**                          | **1743** |   **89** |  **402** |   **29** | **94%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/amcvitty/javelin/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/amcvitty/javelin/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/amcvitty/javelin/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/amcvitty/javelin/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Famcvitty%2Fjavelin%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/amcvitty/javelin/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.