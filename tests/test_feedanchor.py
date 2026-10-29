"""Scroll decisions for the transcript feed (feedanchor.FeedAnchor)."""
from feedanchor import ANCLADO, LIBRE, SEGUIR, FeedAnchor


def test_follows_the_tail_by_default():
    a = FeedAnchor()
    assert a.modo == SEGUIR
    assert a.valor(500) == 500
    assert a.alto_minimo(300) == 0


def test_anchored_answer_stays_put_while_content_grows_below():
    a = FeedAnchor(margen_ancla=12)
    a.anclar()
    a.ubicar(1000)                       # answer top at y=1000
    for maximo in (900, 1500, 4000):     # more and more content below
        a.anotar(a.valor(maximo), maximo)
        assert a.valor(maximo) == min(988, maximo)
    assert a.modo == ANCLADO


def test_anchored_short_answer_gets_room_below_to_sit_at_the_top():
    a = FeedAnchor(margen_ancla=12)
    a.anclar()
    a.ubicar(1000)
    # Viewport 400 px high: content must be at least 988 + 400 tall.
    assert a.alto_minimo(400) == 1388


def test_being_at_the_bottom_while_anchored_does_not_switch_to_follow():
    a = FeedAnchor(margen_ancla=0)
    a.anclar()
    a.ubicar(600)
    a.anotar(600, 600)                   # value == maximum: looks like "at the end"
    assert a.modo == ANCLADO


def test_new_content_below_an_anchor_raises_the_flag_and_follow_clears_it():
    a = FeedAnchor()
    a.anclar()
    a.ubicar(100)
    a.contenido_nuevo()
    assert a.nuevo_abajo
    a.ir_al_final()
    assert (a.modo, a.nuevo_abajo, a.valor(700)) == (SEGUIR, False, 700)


def test_new_content_while_following_is_already_visible():
    a = FeedAnchor()
    a.contenido_nuevo()
    assert not a.nuevo_abajo


def test_manual_scroll_releases_the_anchor():
    a = FeedAnchor(margen_final=8)
    a.anclar()
    a.ubicar(1000)
    a.movido_a_mano(300, 2000)
    assert (a.modo, a.valor(2000), a.alto_minimo(400)) == (LIBRE, 300, 0)
    a.movido_a_mano(1995, 2000)
    assert a.modo == SEGUIR


def test_anchor_follows_its_widget_when_rows_above_are_pruned():
    a = FeedAnchor(margen_ancla=10)
    a.anclar()
    a.ubicar(1000)
    a.ubicar(700)                        # 300 px of old rows removed above
    assert a.valor(5000) == 690


def test_anchor_whose_widget_is_gone_is_released_without_jumping():
    a = FeedAnchor()
    a.anclar()
    a.ubicar(None)
    assert a.modo == LIBRE
    assert a.alto_minimo(400) == 0


def test_anchor_before_layout_behaves_like_follow():
    a = FeedAnchor()
    a.anclar()
    assert a.valor(250) == 250
    assert a.alto_minimo(400) == 0
