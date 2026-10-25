"""How the real-browser writing journeys move between the studio's spaces (SPEC_16A).

The three spaces are not a row of buttons any more: the current space's name in the breadcrumb is a menu, and a space is a radio item in it.
"""


def open_space(page, name):
    page.locator('.studio-space-btn').click()
    page.get_by_role('menuitemradio', name=name).click()
