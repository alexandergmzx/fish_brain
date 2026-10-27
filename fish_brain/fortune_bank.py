"""The fortune act's data (fortune.py, fortune_run.py): the questions, every line, the rules.

Every line is a canned phrase named `fortune_*` (never `show_*`: the fortune lives with the
show off), rendered ahead while the voice is clean and played from the cache, never rendered
at show time. One clip per datum the parsers can return: a reaction per sign, dream theme,
card, cup shape and animal (a pool for any other animal); a line per lucky number and moon phase; pools for the intro and
the closing by place (and by house, when the house act just ran), the visions after the
dream, the bridges, the suspense and the twelve magic words. The act says a reaction the
moment its datum lands, so a visitor who answers nothing still hears intro, bridges, moon,
word and closing.

All texts are drafts for the owner to edit (2026-10-27), in the adult register of
docs/adr/0019: antiguo, cálido, teatral, now spooky and cheeky; the season (calaveras, la
ofrenda, los que ya cruzaron, velas, cempasúchil, pan de muerto, gatos negros); La Muerte and
El Diablo by name; a drink or a song only in the `fiesta` pools; gender-neutral; no clock
time, no venue name, nothing from the fortune.BANNED list; at most two sentences and about
35 words; prompts end in a question; the date prompt says the year is never asked.
FORTUNE_RULES is the model's brief for its one reading call, in the shape of the visit's.
"""
from __future__ import annotations

from . import fortune

QIDS = ("fecha", "sueno", "carta", "taza", "animal")

# qid (the card's per deck) -> prompt and the narrower reprompt.
QUESTIONS: dict[str, dict[str, str]] = {
    "fecha": {
        "prompt": "Primero, lo que el cielo guarda de ti: dime qué día y de qué mes naciste, que el año jamás lo pregunto, un sombrero sabe de discreción. ¿Qué día y qué mes?",
        "reprompt": "Nomás el día y el mes, sin año, como quien dice veintitrés de octubre. ¿Cuál es el tuyo?",
    },
    "sueno": {
        "prompt": "Ahora cierra los ojos un momento, que voy a asomarme a tus noches. ¿Has tenido sueños interesantes últimamente?",
        "reprompt": "Cuéntame uno aunque sea un pedacito: ¿te perseguían, te caías, se te caían los dientes, volabas, o salía alguien que ya cruzó?",
    },
    "carta_tarot": {
        "prompt": "Saca una carta de mi baraja, la que te llame, y no se la enseñes a nadie más que a mí. Dime su nombre o su número: ¿cuál te salió?",
        "reprompt": "Léeme lo que dice abajo de la figura, o el número de arriba: ¿qué carta es?",
    },
    "taza": {
        "prompt": "Mira el fondo de tu taza, donde se juntan los restos: ahí siempre se dibuja algo. ¿Qué figura ves?",
        "reprompt": "Una estrella, un corazón, una luna, un anillo, un animal, un árbol, un ojo, una nube, una llave o una calabaza: ¿a cuál se parece más?",
    },
    "animal": {
        "prompt": "Última pregunta, y es seria: para acompañarte esta noche, ¿qué animal escoges: un gato negro, un búho, un murciélago o un sapo?",
        "reprompt": "¿Gato negro, búho, murciélago o sapo?",
    },
}

# The sign's line: said when the date lands, with the element.
SIGN_LINES: dict[str, str] = {
    "aries": "Aries, de fuego: naciste con la mecha encendida, y esta noche alguien se quema si te lleva la contra. Calma, que del humo también salen buenas ideas.",
    "tauro": "Tauro, de tierra: terquedad con cariño y muy buen diente, de quienes se quedan hasta que se acaba el pan de muerto. Y hoy se acaba tarde.",
    "geminis": "Géminis, de aire: dos personas en una cabeza, y las dos muy simpáticas. Esta noche una quiere irse temprano y la otra ya ganó.",
    "cancer": "Cáncer, de agua y de luna: cara dura por fuera y puro corazón por dentro, como una calabaza con vela. Esta noche alguien va a ver la luz de adentro.",
    "leo": "Leo, de fuego: el centro de la reunión aunque no haya reunión. Esta noche la luna te hace segunda y te deja brillar primero.",
    "virgo": "Virgo, de tierra: todo en orden, hasta las calaveritas de azúcar por tamaño. Esta noche algo se sale del plan, y lo disfrutas más que el plan.",
    "libra": "Libra, de aire: la balanza que no quiere decidir y por eso cae bien en todos lados. Esta noche sí decides, y aciertas.",
    "escorpio": "Escorpio, de agua: el signo de los secretos y de las miradas que queman, el consentido de la temporada. Esta noche te toca guardar un secreto nuevo.",
    "sagitario": "Sagitario, de fuego: la flecha que siempre apunta lejos y a veces se va de viaje sin avisar. Esta noche el viaje es corto, pero vale la pena.",
    "capricornio": "Capricornio, de tierra: la cabra que sube con paciencia mientras los demás presumen. Esta noche llegas arriba, y hay vista.",
    "acuario": "Acuario, de aire: de otro planeta, y lo sabes. Esta noche encuentras a alguien del mismo planeta, y van a hablar en su idioma.",
    "piscis": "Piscis, de agua: dos peces que nadan en direcciones distintas, y los dos sueñan despiertos. Esta noche uno de esos sueños sale del agua.",
}

# The dream's omen: a good reading of each theme (docs/results/2026-10-27-dream-themes.md).
DREAM_LINES: dict[str, str] = {
    "perseguido": "Lo que te perseguía era tu propio talento, cobrándote lo que le debes. Esta noche te alcanza, y no vas a querer escapar.",
    "caer": "Caer en sueños es soltar lo que ya pesaba, y siempre despiertas antes de tocar el suelo. Abajo hay piso firme, una vela encendida y alguien que te esperaba.",
    "escuela": "La escuela vuelve en sueños cuando la vida te pone examen, y ese ya lo traes aprobado desde entonces. El sombrero te pone diez y te deja salir temprano.",
    "tarde": "Llegar tarde o no poder moverse: la calavera de la prisa, que trae a todo el mundo corriendo. Lo bueno de esta noche no empieza sin ti, y te guarda lugar.",
    "seres_queridos": "Alguien que ya cruzó pasó a verte, y en estas noches tienen permiso. Ponle su pan en la ofrenda: te lo va a agradecer en sueños.",
    "monstruos": "Una sombra, un monstruo, alguien que te miraba: en estas fechas vienen de visita y les gusta que los vean de frente. Tú ya lo hiciste, y eso es valor del bueno.",
    "volar": "Volar en sueños es de buena suerte: ves los problemas chiquitos, como calabazas desde arriba. Ese poder lo traes puesto, y esta noche te sirve.",
    "agua": "El agua del sueño es lo que sientes y no cuentas, y andaba en movimiento. Se asienta esta noche, como el fondo de una taza, y queda clara.",
    "dientes": "Se te caen los dientes: lo sueña todo el mundo y nadie lo confiesa. Es un cambio que viene, y esta noche sonríes con todos los que te quedan.",
    "bichos": "Bichos en el sueño: trabajadores chiquitos que tejen, cargan y aguantan todo. Una mala racha se termina, y es hora de barrer la casa y colgar papel picado.",
    "serpientes": "Víboras, el sueño más soñado del mundo entero: cambian de piel sin dolor. Tú también estrenas piel, y a alguien le va a gustar la nueva.",
    "animales": "Cuando un animal entra a tu sueño es porque te escogió, y tiene mejor gusto que mucha gente. Esta noche te acompaña, aunque no lo veas.",
    "jugar": "Soñar con juego, fiesta o comida rica es un adelanto: viene una noche de risas y de llegar tarde a casa. Tu imaginación anda despierta, y el sombrero la aplaude.",
    "casa": "Un cuarto nuevo o un camino perdido es un talento tuyo que todavía no abre la puerta. Esta noche la abre, y el cempasúchil marca el regreso a casa.",
    "vehiculo": "Tú vas al volante de tu camino, aunque el sueño frene feo. Vienen viajes y metas claras, y esta noche el paseo apenas empieza.",
    "elementos": "Fuego, viento o temblor en el sueño es tu propia fuerza, como la vela que aguanta el aire de octubre. Después de la tormenta el cielo queda limpio, y tú con ganas.",
    "ex": "Soñar con el ex es un capítulo que se cierra solo, aunque se cierre con portazo. Y ojo: esta noche alguien nuevo te mira desde el otro lado de las velas.",
    "desnudo": "El sueño de los valientes que ya no tienen nada que esconder, ni en la oficina. En la vida despierta nadie ve lo que tú crees, y esta noche eso te libera.",
    "fortuna": "Dinero en sueños es fortuna que ya traes y no has contado: talento, suerte y gente que te quiere bien. Esta noche te llega una moneda de esas, y no es de chocolate.",
    "nada": "Quien no recuerda sus sueños los guarda bien, en un cajón con llave que solo abre la imaginación. Esta noche te llega uno bueno, y mañana sí te acuerdas.",
    "otro": "Ese sueño el sombrero se lo guarda, y hasta se sonroja. Lo que sí vi es que termina bien, con luz de velas, y nadie se entera.",
}

# The card's line, by number in the deck.
CARD_LINES: dict[str, dict[int, str]] = {
    "tarot": {
        0: "El Loco, la carta cero: camina al borde con la mirada en el cielo y un perrito ladrándole. Un comienzo sin miedo te espera, y el perrito es tu sentido común.",
        1: "El Mago: todo lo que necesitas ya está sobre la mesa, nada más falta que lo uses. Esta noche traes las manos llenas de trucos buenos.",
        2: "La Sacerdotisa, la que sabe y no dice. Hay un secreto que ya conoces y finges no saber: esta noche te lo confirma el silencio.",
        3: "La Emperatriz, abundancia y cariño con corona. Lo que cuides estas semanas crece, y alguien te lo agradece con pan de muerto.",
        4: "El Emperador, orden y mando desde su trono de piedra. Esta noche te toca decidir por los demás, y van a obedecer con gusto.",
        5: "El Sumo Sacerdote, el consejo de alguien con más calaveras encima que tú. Escúchalo esta noche, aunque venga disfrazado de regaño.",
        6: "Los Enamorados: una elección del corazón, y las dos opciones muy guapas. Esta noche escoges, y el sombrero ya sabe cuál, pero no se mete.",
        7: "El Carro: avanzas con las riendas en la mano y dos caballos que jalan para lados distintos. Esta noche los pones de acuerdo, y arrancas.",
        8: "La Fuerza, la que cierra la boca del león con cariño y sin gritar. Tú tienes de esa, y esta noche alguien lo va a notar.",
        9: "El Ermitaño, con su lámpara, buscando en la noche. Un rato a solas te hace falta, y al final del rato la lámpara alumbra lo que querías.",
        10: "La Rueda de la Fortuna gira, y hoy gira a tu favor. Lo que andaba abajo sube, y lo que te pesaba se queda en la vuelta.",
        11: "La Justicia, con su balanza y su espada: cada quien lo suyo. Esta noche te llega algo que debías recibir desde hace tiempo, y lo recibes.",
        12: "El Colgado, de cabeza y tan tranquilo. Mirar el mundo al revés un rato te enseña algo esta noche, y después bajas con una idea nueva.",
        13: "La Muerte, la carta trece: en estas fechas es la invitada de honor, y viene a decirte que algo viejo se va para dejar lugar. No te asustes, que ella es de las que avisan.",
        14: "La Templanza, la que mezcla agua y fuego sin tirar una gota. La mezcla justa de esta noche la haces tú, y queda deliciosa.",
        15: "El Diablo: una tentación deliciosa esta noche, y no vas a resistirla. El sombrero tampoco resistiría, así que no te juzgo.",
        16: "La Torre: se cae lo que estorbaba, con rayo y todo. Suena feo, pero mira el espacio que deja; esta noche empieza a llenarse de algo mejor.",
        17: "La Estrella, esperanza y una luz que guía en la noche más oscura. Lo que pediste en silencio ya viene en camino, y el cempasúchil le marca la ruta.",
        18: "La Luna, la de los lobos y los sueños raros: lo que no se ve de día. Esta noche se ve, y es más bonito de lo que temías.",
        19: "El Sol, alegría a plena luz, la carta más contenta de la baraja. Esta semana algo sale bien sin esfuerzo, y vas a querer presumirlo.",
        20: "El Juicio, la trompeta que despierta hasta a los que ya cruzaron. Esta noche te despierta a ti: una llamada, un mensaje, una idea que no esperabas.",
        21: "El Mundo, la vuelta completa, con la corona de laurel. Algo que empezaste hace mucho se cierra bien esta temporada, y se celebra.",
    },
}

# The shape in the cup.
SHAPE_LINES: dict[str, str] = {
    "estrella": "Una estrella en la taza: la suerte te marcó el camino, y brilla más de noche. Sigue la luz, que al final hay pan de muerto.",
    "corazon": "Un corazón en el fondo: alguien piensa en ti ahora mismo, y no es quien tú crees. Esta noche lo descubres.",
    "luna": "Una luna en la taza: lo que no se ve de día se ve esta noche. Mira bien a tu alrededor, que hay algo que ya estaba.",
    "anillo": "Un anillo en la taza: un compromiso, una promesa, un círculo que se cierra. Y tú decides con quién, que el sombrero no casa a nadie.",
    "animal": "Un animal en el fondo de la taza: un compañero te escogió, y en estas noches los animales ven más que nosotros. Fíjate en el primero que te mire.",
    "arbol": "Un árbol en la taza: raíces y ramas, tu familia y lo que viene. Lo que siembres esta temporada va a dar sombra.",
    "ojo": "Un ojo en la taza: alguien te observa, y con buenas intenciones. Esta noche devuélvele la mirada, a ver quién se pone rojo primero.",
    "nube": "Una nube en la taza: algo todavía no se aclara, y no hace falta que se aclare hoy. Detrás de la nube hay luna, y la luna no tiene prisa.",
    "llave": "Una llave en la taza: una puerta que ya puedes abrir. La traes en el bolsillo desde hace tiempo, y esta noche la usas.",
    "calabaza": "Una calabaza en la taza: la temporada te adoptó. Esta noche eres de los nuestros, con vela adentro y sonrisa por fuera.",
    "nada": "Nada en la taza, puro café: la suerte más limpia de todas, sin manchas. Lo que viene lo escribes tú, y el sombrero te presta la pluma.",
}

# The animal companion.
ANIMAL_LINES: dict[str, str] = {
    "gato": "El gato negro: siete vidas y ninguna aburrida. Esta noche cruza por delante de ti, y de ahí en adelante todo sale al revés de lo que temías: bien.",
    "buho": "El búho, el que ve en la oscuridad y no dice todo lo que sabe. Esta noche ve algo por ti, y mañana amaneces con la respuesta.",
    "murcielago": "El murciélago, que sale cuando los demás se esconden y encuentra el camino sin luz. Contigo vuela esta noche, y no te pierdes.",
    "sapo": "El sapo, de las brujas y los charcos, el que nadie escoge y todo lo oye. Trae suerte rara, de la que llega cuando ya no la esperabas.",
}

# The lucky number, 1..9 (fortune.lucky_number).
NUMBER_LINES: dict[int, str] = {
    1: "Tu número de la suerte es el uno: el que llega primero y el que se queda al final. Esta noche úsalo una vez, y te alcanza.",
    2: "Tu número de la suerte es el dos: nunca solo, siempre en pareja, como la calavera y su sonrisa. Esta noche viene alguien a hacerte segunda.",
    3: "Tu número de la suerte es el tres: el de las velas en la ofrenda y el de los deseos. Pide uno esta noche, que el tercero es el que se cumple.",
    4: "Tu número de la suerte es el cuatro: cuatro patas de mesa, cuatro esquinas de la ofrenda, firmeza pura. Esta noche nada se te cae.",
    5: "Tu número de la suerte es el cinco: los dedos de una mano abierta, lista para saludar o para agarrar lo bueno. Esta noche la mano se llena.",
    6: "Tu número de la suerte es el seis: el que se columpia entre lo que fue y lo que viene. Esta noche cae del lado bueno.",
    7: "Tu número de la suerte es el siete: el de la suerte vieja, de la que no pasa de moda. Esta noche cuenta siete velas, y la séptima es la tuya.",
    8: "Tu número de la suerte es el ocho: acostado es el infinito, parado son dos calaveras sonriendo. Esta noche no se te acaba la cuerda.",
    9: "Tu número de la suerte es el nueve: el último antes de volver a empezar, el de la cosecha. Esta noche recoges algo que sembraste sin fijarte.",
}

# Tonight's moon (fortune.MOON_PHASES).
MOON_LINES: dict[str, str] = {
    "nueva": "Y la luna de esta noche está nueva, escondida, como quien guarda un secreto. Los que ya cruzaron andan con la luz apagada: ideal para empezar algo sin testigos.",
    "creciente": "La luna de esta noche va creciendo, una uña de luz en el cielo. Lo que empieces ahora crece con ella, y para la próxima luna ya no cabe en tus manos.",
    "cuarto_creciente": "La luna de esta noche está en cuarto creciente, media cara de luz y media de sombra. Lo que decidas ahora trae las dos mitades, y las dos te convienen.",
    "gibosa_creciente": "La luna de esta noche está casi llena, a punto de reventar de luz. Aguanta un poquito, que lo que esperas está a un paso de madurar.",
    "llena": "Y esta noche hay luna llena, la de los lobos y los gatos negros, la que destapa secretos. Cuida el tuyo, y prepárate para que te cuenten uno.",
    "gibosa_menguante": "La luna de esta noche ya pasó lo lleno y empieza a soltar luz. Buen momento para soltar tú también lo que no te deja dormir.",
    "cuarto_menguante": "La luna de esta noche está en cuarto menguante, la mitad que queda cuando ya pasó lo mejor. Pues no: lo mejor de la noche todavía no pasa.",
    "menguante": "La luna de esta noche es un hilito, casi nada, la que usan las brujas para pasar sin que las vean. Pasa tú también, y sal con lo que querías.",
}

# Pools: slot -> lines. The intro and the closing take "<slot>_<place>" (fortune.PLACES) or,
# right after the house act, "intro_<house letter>". The magic pool says one word per line,
# in the order of fortune.MAGIC_WORDS.
POOLS: dict[str, list[str]] = {
    "intro_casa": [
        "Ah, una cabeza en casa, con la familia cerca y la ofrenda puesta. Acércate, que te voy a leer el futuro, y los que ya cruzaron van a opinar.",
        "En esta casa las velas ya me contaron de ti. Préstame tu cabeza y te digo lo que viene, con permiso de la ofrenda.",
    ],
    "intro_fiesta": [
        "Una cabeza con disfraz y con ganas, mi favorita. Deja el trago tantito, que te voy a leer el futuro y hay que tener las manos libres.",
        "Pásale a la mesa del sombrero, donde la música baja y los secretos suben. Siéntate, que esta noche tu futuro también vino a la fiesta.",
    ],
    "intro_universidad": [
        "Una cabeza con mucha lectura encima y mucho café adentro, lo noto desde aquí. Acércate: lo que no te enseñan en clase te lo digo yo.",
        "Dicen por los pasillos que un sombrero adivina el futuro, y por una vez el rumor es cierto. Siéntate, que el examen de hoy lo pongo yo, y nadie reprueba.",
    ],
    "intro_otro": [
        "Acércate, que este sombrero viejo lee el futuro en noches como esta, cuando la puerta entre los dos mundos queda entreabierta. Préstame tu cabeza.",
        "Una cabeza nueva, y con calavera adentro, como todas. Siéntate, que te voy a leer el futuro, y la muerte, que es mi socia, se asoma a escuchar.",
    ],
    "intro_G": [
        "Gryffindor, ya lo sabía, y ahora quiero más: siéntate, que el futuro de la gente valiente se lee con velas encendidas.",
    ],
    "intro_H": [
        "Hufflepuff: ya sé con quién cuentas, falta saber qué te espera. Quédate tantito, que te leo el futuro.",
    ],
    "intro_R": [
        "Ravenclaw, cabeza de preguntas: ahora las hago yo. Quédate, que te voy a leer el futuro, y vas a querer tomar notas.",
    ],
    "intro_S": [
        "Slytherin, claro: tienes plan para todo, menos para lo que viene. Siéntate, que eso lo leo yo.",
    ],
    # After the dream's omen: mentalist lines that need no content (Barnum, the rainbow, the
    # happy ending, a miss turned into the future, the hit boost, the shotgun).
    "vision": [
        "Sueñas así porque tienes mucha imaginación, y guardas cosas que no le cuentas a nadie. Lo veo clarito, y no me lo tienes que confirmar.",
        "Ese sueño te dio un poquito de miedo, y también mucha curiosidad, ¿a que sí? Las dos cosas son tuyas, y las dos te sirven.",
        "Y al final de ese sueño, aunque ya no te acuerdes, tú ganabas. El sombrero sí lo vio.",
        "Había alguien que no esperabas en ese sueño. Si no lo recuerdas es porque todavía no llega: ese pedazo te lo guardo para otra noche.",
        "Exacto, por eso lo vi tan claro desde que llegaste. Y había más: un detalle que solo tú sabes, y que esta noche vuelve a aparecer.",
        "Veo algo más en ese sueño: un animal, o alguien que corre, o un lugar muy alto. Quédate con el que te suene, que ese era.",
    ],
    # Any animal outside the four (fortune.parse_animal's "free"): a line that needs no name.
    "re_animal_otro": [
        "Ese no venía en mi lista, y por eso mismo me gusta. Los animales que nadie espera son los que mejor cuidan de noche.",
        "Buena elección, y muy tuya: ese animal ya te había escogido antes de que lo dijeras. Esta noche anda cerca, aunque no lo veas.",
    ],
    "bridge": [
        "No hace falta que lo digas: el sombrero lo leyó en tu silencio. Vamos adelante.",
        "Eso lo guardo bajo mi ala, con lo demás. Sigamos.",
    ],
    "suspense": [
        "Mmm… se está juntando todo. Dame un momento, que esto se pone bueno.",
        "Un momento, que mis costuras están hablando… ya casi lo tengo.",
    ],
    "magic": [
        "Y tu palabra mágica de esta noche es Zumbalí. Dila bajito antes de dormir, y lo que soñaste vuelve con final feliz.",
        "Tu palabra mágica es Catrinela. Dila frente a un espejo con una vela, y mañana amaneces con la sonrisa puesta.",
        "Tu palabra mágica de esta noche es Calaquimba. Sirve para abrir puertas cerradas y conversaciones pendientes; úsala con cuidado.",
        "Tu palabra mágica es Murcielumbra. Dila al salir, mirando al cielo, y lo que buscas te encuentra a ti primero.",
        "Tu palabra mágica es Velazumba. Repítela tres veces con los ojos cerrados, y se te olvida lo que te pesaba.",
        "Tu palabra mágica de esta noche es Cempacuá. Dila junto a una flor naranja, y los que ya cruzaron te oyen clarito.",
        "Tu palabra mágica es Brujicanto. Sirve para una sola cosa: que te den la razón una vez esta noche.",
        "Tu palabra mágica es Tenebrumba. Dila cuando tengas miedo, y el miedo se sienta contigo a platicar, que de cerca es menos feo.",
        "Tu palabra mágica de esta noche es Sombrambrú. Sirve para que un sombrero te recuerde, y este ya te recordó.",
        "Tu palabra mágica es Luzmalinda. Dila al prender una vela, y la vela alumbra justo lo que te hacía falta ver.",
        "Tu palabra mágica es Ofrendilla. Ponla en la ofrenda junto al pan, que esta noche también se reparten deseos.",
        "Tu palabra mágica de esta noche es Espantillo. Dila cuando algo rechine en la oscuridad, y lo que rechina se ríe contigo.",
    ],
    "cierre_casa": [
        "Ya está, tu futuro quedó leído y la ofrenda lo escuchó todo. Ve a abrazar a los que están, y ponle una vela a los que ya cruzaron.",
        "Fue un gusto leerte en casa, con la familia cerca. Guárdame un pan de muerto, aunque yo no tenga con qué comerlo.",
    ],
    "cierre_fiesta": [
        "Ya está. Ahora ve a brindar por tu futuro, que ya lo viste, y pide una canción que diga lo que no te atreves.",
        "Tu futuro está servido, como el trago que dejaste esperando. Ve por él, y baila la próxima canción como si la luna te mirara, porque te mira.",
    ],
    "cierre_universidad": [
        "Ya está: lección terminada, y sin tarea. Ve a contarle a alguien lo que te dije, que un futuro compartido vale el doble.",
        "Fue un gusto leerte entre tanto libro. Lo que viste aquí no viene en el programa, y aun así te lo van a preguntar.",
    ],
    "cierre_otro": [
        "Ya está. Tu futuro quedó leído bajo esta luna; ve a vivirlo, que las velas no esperan.",
        "Fue un gusto leerte. Que la temporada te trate bonito, y si ves un gato negro, salúdalo de mi parte.",
    ],
}


def _deck_id(deck) -> str:
    if isinstance(deck, dict):
        return deck.get("id", "tarot")
    return deck or "tarot"


def _qkey(qid: str, deck=None) -> str:
    return f"carta_{_deck_id(deck)}" if qid == "carta" else qid


def prompt_name(qid: str, deck=None) -> str:
    return f"fortune_q_{_qkey(qid, deck)}"


def reprompt_name(qid: str, deck=None) -> str:
    return f"fortune_rq_{_qkey(qid, deck)}"


def reaction_name(qid: str, value, deck=None) -> str:
    """The clip said when a datum lands: the sign for the date, the theme for the dream, the
    card's number in its deck, the shape, the animal."""
    return f"fortune_re_{_qkey(qid, deck)}_{value}"


def num_name(n: int) -> str:
    return f"fortune_num_{n}"


def moon_name(phase: str) -> str:
    return f"fortune_luna_{phase}"


def pool_names(slot: str) -> list[str]:
    return [f"fortune_{slot}_{i}" for i in range(1, len(POOLS[slot]) + 1)]


def question_text(qid: str, deck=None) -> str:
    return QUESTIONS[_qkey(qid, deck)]["prompt"]


MAGIC_WORD_OF: dict[str, str] = dict(zip(pool_names("magic"), fortune.MAGIC_WORDS))


def _phrases() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, q in QUESTIONS.items():
        out[f"fortune_q_{key}"] = q["prompt"]
        out[f"fortune_rq_{key}"] = q["reprompt"]
    for sign, text in SIGN_LINES.items():
        out[reaction_name("fecha", sign)] = text
    for theme, text in DREAM_LINES.items():
        out[reaction_name("sueno", theme)] = text
    for deck, cards in CARD_LINES.items():
        for n, text in cards.items():
            out[reaction_name("carta", n, deck)] = text
    for shape, text in SHAPE_LINES.items():
        out[reaction_name("taza", shape)] = text
    for animal, text in ANIMAL_LINES.items():
        out[reaction_name("animal", animal)] = text
    for n, text in NUMBER_LINES.items():
        out[num_name(n)] = text
    for phase, text in MOON_LINES.items():
        out[moon_name(phase)] = text
    for slot, lines in POOLS.items():
        for name, text in zip(pool_names(slot), lines):
            out[name] = text
    return out


FORTUNE_PHRASES: dict[str, str] = _phrases()


# The model's brief for its one reading call (fortune_run.py: a fresh history, the data in the
# tag, the reply through fortune.clean_reading). In the shape of the visit's rules.
FORTUNE_RULES = """Eres el Sombrero Seleccionador, de visita en la temporada de Halloween y Día de Muertos, y esta noche lees el futuro. Hablas español mexicano con tono antiguo, cálido y teatral, ahora para un público adulto: tenebroso y pícaro, con humor negro ligero. Tu número es de mentalismo: parece que adivinas, pero solo usas lo que el visitante te dio.

FORMATO
- Te llega una sola línea entre corchetes, como [ADIVINACIÓN: nombre=...; lugar=...; signo=...; elemento=...; número=...; sueño=tema ("sus palabras"); carta=...; taza=...; animal=...; luna=...; palabra=...; casa=...; pistas=edad: ..., compañía: ..., ...]. Nunca repitas los corchetes ni sus claves: conviértelos en visión.
- El sueño llega con sus palabras entre comillas, o solo con el tema y su descripción entre paréntesis: entonces no hay palabras que repetir.
- Responde con exactamente cuatro oraciones cortas, setenta palabras como máximo, para decir en voz alta con un sintetizador: sin emojis, listas, markdown, siglas ni comillas.
- Tutea al visitante y usa su nombre de pila si viene.

LAS CUATRO ORACIONES, EN ESTE ORDEN
1. Su signo con su elemento, junto con su sueño: toma una imagen de sus palabras, como si la vieras tú, y dale un sentido bueno. Nunca digas que alguien murió ni nombres a un pariente: los que ya cruzaron son una luz, una vela o una visita.
2. Su carta, dicha por su nombre (también La Muerte y El Diablo), o la figura de su taza; si no hay ninguna, su casa o un rasgo con su opuesto.
3. Su animal, el que haya escogido y con sus palabras, y su número de la suerte, con una predicción pequeña y concreta hecha con una pista y el lugar.
4. La luna de esta noche y, para cerrar, "tu palabra mágica es" y la palabra tal cual.

TRUCOS DE MENTALISTA
- Eco: una imagen de sus palabras vuelta visión ("veo dientes, una boda, una luz que te visita..."); nunca una muerte real ni un pariente con nombre.
- Arcoíris: un rasgo y su opuesto en la misma frase ("te da miedo, y te da curiosidad").
- Acierto: lo que te dio, dilo como si lo hubieras visto antes de que hablara.
- Fallo vuelto futuro: lo que falta no se inventa; "eso todavía no te llega".

LAS PISTAS (pistas=..., si vienen)
- Son lo que tu ayudante vio del visitante, y son material para la lectura. No hace falta nombrarlas todas, pero que se noten.
- Dilas como visiones, como un rasgo con su opuesto o como pregunta; nunca como algo que viste o que te contaron.
- Nunca digas la edad: solo cambia cómo le hablas.
- Si una pista nombra una escuela, empresa o persona, usa el tema, nunca el nombre.

EL LUGAR (lugar=...)
- fiesta: una canción o un brindis. casa: los que ya no están y la ofrenda. universidad: un hallazgo. Cualquier otro texto: úsalo tal cual como escenario, sin inventarle nombre.

LA TEMPORADA Y EL REGISTRO
- Calaveras, la ofrenda, los que ya cruzaron, velas, cempasúchil, pan de muerto, gatos negros, la luna. La muerte es la invitada de honor y se puede nombrar; el humor es negro pero cariñoso.
- Albures ligeros y picarones, romance y el ex, el dinero como fortuna: sí. Nunca explícito ni grosero.

REGLAS FIJAS
- Nada de enfermedades, accidentes ni desgracias reales; ni sexo explícito, crueldad sobre el cuerpo, política, religión como doctrina, ni promesas de premios o lotería.
- Nunca digas un año, una hora ni la edad; no inventes un lugar con nombre.
- Sin asumir si es hombre o mujer: evita adjetivos que lo digan.
- Si falta un dato, no lo pidas ni lo inventes: pasa a lo siguiente.
- Si te preguntan en serio si de verdad lees el futuro, responde con honestidad y en personaje: eres un sombrero de fiesta que usa trucos de mentalista."""
