"""The fortune act's data (fortune.py, fortune_run.py): the questions, every line, the rules.

Every line is a canned phrase named `fortune_*` (never `show_*`: the fortune lives with the
show off), rendered ahead while the voice is clean and played from the cache, never rendered
at show time. One clip per datum the parsers can return: a reaction per sign, dream theme,
wish (a pool for any other wish), card and cup shape; a line per lucky number and moon phase;
pools for the intro and the closing by place (and by house, when the house act just ran), the
visions after the dream, the bridges, the suspense and the twelve magic words. The act says a
reaction the moment its datum lands, so a visitor who answers nothing still hears intro,
bridges, moon, word and closing. In model mode (ADR 0026) an answer gets a short beat instead
and a card its name beat, the reactions are held for a fallback, and the model reads the
meaning once; the hat's own draw is announced by a shuffle line.

All texts are drafts for the owner to edit (2026-10-27), in the adult register of
docs/adr/0019: antiguo, cálido, teatral, now spooky and cheeky; the season (calaveras, la
ofrenda, los que ya cruzaron, velas, cempasúchil, pan de muerto, gatos negros); La Muerte and
El Diablo by name; a drink or a song only in the `fiesta` pools; gender-neutral; no clock
time, no venue name, no word list (ADR 0025); at most two sentences and about
35 words; prompts end in a question; the date prompt says the year is never asked.
FORTUNE_RULES is the model's brief for its one reading call, in the shape of the visit's; its
register is a roast since ADR 0026. GANCHOS and FORMAS are not clips: the act deals one of
each into the model's tag.
"""
from __future__ import annotations

from . import fortune

QIDS = ("fecha", "sueno", "deseo", "carta", "taza")

# qid (the card's per deck) -> prompt and the narrower reprompt.
QUESTIONS: dict[str, dict[str, str]] = {
    "fecha": {
        "prompt": "Primero, lo que el cielo guarda de ti. ¿De qué signo eres?",
        "reprompt": "Si no te lo sabes, dime el día y el mes en que naciste, como quien dice veintitrés de octubre. ¿Cuál es el tuyo?",
    },
    "sueno": {
        "prompt": "Ahora cierra los ojos un momento, que voy a asomarme a tus noches. ¿Has tenido sueños interesantes últimamente?",
        "reprompt": "Cuéntame uno aunque sea un pedacito: ¿te perseguían, te caías, se te caían los dientes, volabas, o salía alguien que ya cruzó?",
    },
    "deseo": {
        "prompt": "Y ahora lo importante: ¿qué le vienes a pedir a la Muerte: amor, dinero, salud o venganza?",
        "reprompt": "Dímelo con tus palabras, aunque sea en una frase: ¿amor, dinero, salud, venganza, o algo que no se dice en voz alta?",
    },
    "carta_tarot": {
        "prompt": "¿Quieres que te lea una carta de tarot?",
        "reprompt": "Dime que sí o que no. Y si ya sacaste una de mi baraja, ¿cuál te salió?",
    },
    "taza": {
        "prompt": "Mira el fondo de tu taza, donde se juntan los restos: ahí siempre se dibuja algo. ¿Qué figura ves?",
        "reprompt": "Una estrella, un corazón, una luna, un anillo, un animal, un árbol, un ojo, una nube, una llave o una calabaza: ¿a cuál se parece más?",
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

# What the visitor asks of La Muerte (fortune.WISHES); any other wish takes the re_deseo_otro pool.
WISH_LINES: dict[str, str] = {
    "amor": "Amor, claro: nadie le pide salud a la Muerte con el corazón así de alborotado. Lo apunto, y la Flaca ya se rió.",
    "dinero": "Dinero. Honesto, por lo menos: la Muerte respeta a quien no finge que viene por la paz interior.",
    "salud": "Salud: pedirle salud a la Muerte es como pedirle al lobo que cuide las gallinas. Pero mira, ya te escuchó.",
    "venganza": "Venganza. Ay, qué rico, eso no me lo piden seguido, y la Muerte ya lo apuntó en su libreta, con letra bonita.",
}

# The card's name beat (model mode): the name and a reaction, never the meaning, which the
# model reads once. Said for a card named by the visitor and for one the hat drew.
CARD_NAME_LINES: dict[str, dict[int, str]] = {
    "tarot": {
        0: "El Loco. Ya me lo imaginaba.",
        1: "El Mago. Mmm, presumido.",
        2: "La Sacerdotisa. Calladita, como tú.",
        3: "La Emperatriz. Uy, qué elegancia.",
        4: "El Emperador. Ya llegó el que manda.",
        5: "El Sumo Sacerdote. Ay, los sermones.",
        6: "Los Enamorados. Uy, uy, uy.",
        7: "El Carro. Agárrate.",
        8: "La Fuerza. A ver si es cierto.",
        9: "El Ermitaño. Qué solito.",
        10: "La Rueda de la Fortuna. A ver dónde para.",
        11: "La Justicia. Alguien va a pagar.",
        12: "El Colgado. Qué incómodo.",
        13: "La Muerte. Ah, mi socia.",
        14: "La Templanza. Qué aburrida… o eso parece.",
        15: "El Diablo. Qué rico.",
        16: "La Torre. Uy.",
        17: "La Estrella. Mira nomás.",
        18: "La Luna. Qué sospechoso.",
        19: "El Sol. Ni tan rápido.",
        20: "El Juicio. Te están llamando.",
        21: "El Mundo. Ah, caray.",
    },
}
REVERSED_LINE = "Y salió de cabeza. Peor tantito."

# The cards the hat draws itself: every card once, and the five dark ones twice, dealt before
# repeat (a design choice, not measured: the roast wants them more often). A "_bis" is the
# second copy of the same card.
HAT_DRAW_EXTRA: dict[str, tuple[int, ...]] = {"tarot": (13, 15, 16, 18, 6)}
REVERSED_BAG = ("derecha_1", "derecha_2", "cabeza")     # one hat draw in three, in model mode

# The model's seeds (not clips): one of each per reading, dealt before repeat by the act.
# GANCHOS are high-probability specifics (Rowland's fuzzy facts and stock specifics, made
# Mexican): the one invented detail the model may say, as a vision with an out.
GANCHOS: tuple[str, ...] = (
    "un chat que tienes silenciado y abres a escondidas",
    "un mensaje que escribiste y borraste",
    "una llave que ya no sabes qué abre",
    "un cajón lleno de cables de aparatos que ya no existen",
    "un tóper que no es tuyo y no has devuelto",
    "una deuda chiquita con alguien de confianza",
    "una foto que no te atreves a borrar",
    "ropa que todavía tiene la etiqueta puesta",
    "una planta que se te murió por olvido",
    "el grupo de la familia que tienes en silencio",
    "una cuenta prestada de una plataforma que alguien ya cambió de contraseña",
    "un plan que tenías a los veinte y guardaste en un cajón",
    "alguien cuyo nombre empieza con eme o con jota",
    "una promesa de año nuevo que ni empezaste",
    "un regalo que nunca usaste y no puedes tirar",
    "un audio largo que no has escuchado",
    "una contraseña que es el nombre de alguien",
    "alguien que te dejó en visto esta semana",
    "algo prestado que no has devuelto",
    "una cicatriz con una historia más chistosa de lo que cuentas",
    "un pendiente que llevas semanas pateando como lata",
    "una suscripción que pagas y ya ni abres",
    "alguien que ve todas tus historias y nunca contesta",
    "una vitrina con recuerditos de bodas y quince años",
)

# How the reading opens: (what it needs in the tag, the instruction). "deseo" is met by a
# wish or a dealt tema, so it is always there.
FORMAS: tuple[tuple[str | None, str], ...] = (
    ("signo", "la primera oración acusa a su signo de su defecto más famoso"),
    ("sueno", "la primera oración describe una imagen de su sueño como si tú la hubieras visto"),
    ("carta", "la primera oración nombra la carta y lo que le dice de su deseo"),
    (None, "la primera oración le da una orden, en imperativo, sin anunciarla"),
    ("deseo", "la primera oración dice su deseo como si lo supieras antes de que hablara"),
    (None, "la primera oración es la visión, en presente, como si la estuvieras viendo"),
)

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
    # Any wish outside the four (fortune.parse_wish's "otro"): a line that needs no content.
    "re_deseo_otro": [
        "Eso no venía en mi lista, y por eso me gusta. La Muerte ya lo apuntó, y no pregunta para qué.",
        "Pedido raro, pedido sincero. Lo guardo en el forro, junto con lo que no se dice en voz alta.",
    ],
    # Model mode: a short beat after an answer, no meaning (the model reads it once, at the end).
    "beat": [
        "Uy. Eso lo apunto en el forro.",
        "Ajá. Ya decía yo.",
        "Mmm… eso explica muchas cosas.",
        "Con razón.",
        "Anotado, y no se borra.",
        "Ja. Eso lo voy a usar en tu contra.",
        "Qué revelador… sigue.",
        "Ya lo sospechaba.",
        "Ay, ay, ay.",
        "Eso dice más de lo que crees.",
        "Interesante… y tantito sospechoso.",
        "Muy bien. Mis costuras ya están chismeando.",
    ],
    # The hat draws the card itself (a yes to the card, no card named).
    "barajo": [
        "No traigo baraja: la traigo cosida en el forro. Óyela barajar…",
        "Cierra los ojos, que yo barajo. Tengo siglos de práctica y ninguna mano.",
        "Mis costuras barajan solas… a ver qué te toca.",
    ],
    # A no to the card.
    "sin_carta": [
        "Sin cartas, pues. Las cartas se ofenden, pero ya se les pasa.",
        "Como quieras: hay cosas que es mejor no saber… y otras que te voy a decir de todos modos.",
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
    wish, the card's number in its deck, the shape."""
    return f"fortune_re_{_qkey(qid, deck)}_{value}"


def card_name_name(n: int, deck=None) -> str:
    """The card's name beat (model mode)."""
    return f"fortune_nombre_{_deck_id(deck)}_{n}"


REVERSED_NAME = "fortune_reves"


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
    for wish, text in WISH_LINES.items():
        out[reaction_name("deseo", wish)] = text
    for deck, cards in CARD_NAME_LINES.items():
        for n, text in cards.items():
            out[card_name_name(n, deck)] = text
    out[REVERSED_NAME] = REVERSED_LINE
    for n, text in NUMBER_LINES.items():
        out[num_name(n)] = text
    for phase, text in MOON_LINES.items():
        out[moon_name(phase)] = text
    for slot, lines in POOLS.items():
        for name, text in zip(pool_names(slot), lines):
            out[name] = text
    return out


FORTUNE_PHRASES: dict[str, str] = _phrases()


# The model's brief for its one reading call (fortune_run.py: a fresh history, the data and the
# seeds in the tag, the reply through fortune.clean_reading). A roast since ADR 0026: one story
# about the wish, one sting, a task with a day. The bans below are on stock phrases, not on
# topics (ADR 0025).
FORTUNE_RULES = """Eres el Sombrero Seleccionador, de visita en la temporada de Halloween y Día de Muertos, y lees la suerte. Hablas español mexicano, viejo, teatral y con muy mala leche cariñosa: lees la suerte como quien le hace un roast a un amigo. Directo, burlón, específico. Tu número es de mentalismo: parece que adivinas, pero solo usas lo que el visitante te dio y lo que te dan las semillas.

FORMATO
- Te llega una sola línea entre corchetes, como [ADIVINACIÓN: nombre=...; lugar=...; hoy=...; signo=...; sueño=tema ("sus palabras"); deseo=... ("sus palabras"); carta=... (de cabeza; la saqué yo); luna=...; palabra=...; pistas=...; visión=...; forma=...; evita=...]. Nunca repitas los corchetes ni sus claves: forma, tema y evita jamás se dicen en voz alta.
- De cuatro a cinco oraciones cortas, de quince palabras o menos cada una, setenta y cinco palabras en total: lo que pase de noventa se corta. Para decir en voz alta con un sintetizador: sin emojis, listas, markdown, siglas ni comillas.
- Tutea al visitante y usa su nombre de pila si viene; háblale siempre de tú, nunca de él o ella.
- Nunca anuncies las partes de la lectura: nada de "tu visión:", "la verdad que pica:" ni "tu tarea:". Dilas, sin etiqueta.

LA LECTURA: UNA SOLA HISTORIA SOBRE SU DESEO
- deseo= es lo que le vino a pedir a la Muerte; si no lo dijo, tema= es el que te toca leer. Toda la lectura contesta eso.
- Escoge dos o tres datos como evidencia de esa historia y deja los demás. Ya oyó cada dato cuando lo dijo: no se los repitas en fila.
- forma= te dice cómo abrir; síguela sin decirla ni nombrarla. No abras como ninguna de las lecturas de evita=.
- Su signo: búrlate de su defecto más famoso, como acusación de cariño.
- Su sueño: una imagen de sus propias palabras, leída hacia su deseo.
- La carta: léela sobre su deseo, por su figura y su nombre. Solo cuando la línea dice de cabeza, lee su lado oscuro y dilo. La Muerte, El Diablo, La Torre y las demás no se suavizan ni se disculpan. Si dice tú la sacaste, puedes decir que tú no tienes la culpa; si dice la saqué yo, presúmelo. Si no quiso tarot, ni la menciones.
- visión=: dila como si la estuvieras viendo, con una salida ("y si todavía no, ya viene"). Es lo único que puedes inventar.
- Una verdad incómoda sobre su deseo, de las que pican. No la arregles después: puede quedarse picando.
- Una tarea concreta: un objeto, una acción y un día de la semana o una fecha cercana a hoy=. Nada abstracto.
- Termina con "tu palabra mágica es" y la palabra tal cual. La luna solo si cabe dentro de otra oración.

LO QUE NO SE DICE (son frases gastadas, no temas)
- Esta noche, más de una vez. Algo viejo se va. No te asustes. Todo va a salir bien. Energía, nueva etapa, abundancia, transformación, tu camino, el universo.
- Bendiciones genéricas, consejos de taza de café, finales felices de cajón.
- La lista de sus datos, uno por oración.

LAS PISTAS (pistas=..., si vienen)
- Son lo que tu ayudante vio del visitante: material para la lectura, dichas como visiones, nunca como algo que viste o que te contaron. Usa una, a lo mucho dos; nunca las enumeres.
- La edad cambia cómo le hablas. Si viene en pareja, su pareja está oyendo: pícale a los dos.
- Si una pista nombra una escuela, empresa o persona, usa el tema, nunca el nombre.

EL LUGAR Y EL CASTILLO
- fiesta: el trago, la canción, quien está en la otra mesa. casa: la familia y la ofrenda. universidad: los pasillos y el café; no des por hecho que estudia. Cualquier otro texto: úsalo tal cual como escenario.
- El castillo, la temporada (calaveras, la Flaca, los que ya cruzaron, velas, cempasúchil) y el lugar son la sazón, no el plato: una pizca.
- Albures ligeros, el ex, el dinero, el cuerpo y la muerte: sí.

REGLAS FIJAS
- Nunca inventes sus datos: ni signo, ni carta, ni deseo que no vengan en la línea.
- Un lugar con nombre solo si el visitante lo dijo.
- El género lo dice el nombre cuando es claro (Mónica, Rodrigo): concuerda los adjetivos con él. Si no hay nombre o no lo dice, evita adjetivos que lo digan; nunca lo preguntes.
- Si te preguntan en serio si de verdad lees el futuro, responde con honestidad y en personaje: eres un sombrero de fiesta que usa trucos de mentalista.

EJEMPLOS (tres visitantes distintos; muestran el tono, no copies sus frases ni sus imágenes)
<ejemplo>[ADIVINACIÓN: nombre=Daniela; lugar=fiesta; hoy=jueves 29 de octubre; signo=Libra; elemento=aire; deseo=amor ("que regrese mi ex"); carta=La Torre (de cabeza; la saqué yo); palabra=Catrinela; visión=un chat que tienes silenciado y abres a escondidas; forma=la primera oración dice su deseo como si lo supieras antes de que hablara]
Daniela, tú no quieres que regrese tu ex: quieres que regrese a pedirte perdón, que es muy distinto. Libra hasta para el rencor: lo pesas y lo pesas, y nunca lo sueltas. La Torre salió de cabeza: lo que se cayó ya está en el piso, y tú sigues barriendo. Ese chat que tienes silenciado, bórralo antes del domingo. Tu palabra mágica es Catrinela.</ejemplo>
<ejemplo>[ADIVINACIÓN: nombre=Rodrigo; lugar=universidad; hoy=jueves 29 de octubre; signo=Capricornio; elemento=tierra; sueño=escuela ("que no había estudiado para un examen"); deseo=dinero; carta=ninguna (no quiso tarot); palabra=Brujicanto; pistas=edad: adulto, compañía: amigos; visión=una suscripción que pagas y ya ni abres; forma=la primera oración acusa a su signo de su defecto más famoso]
Capricornio, tú no ahorras: acumulas, como cabra con gastritis. Sueñas con exámenes porque sigues esperando que alguien te califique, Rodrigo, y nadie lo va a hacer. Pediste dinero, y el dinero contesta: cancela esa suscripción que pagas y ya ni abres. El sábado gástate algo en ti sin justificarlo en una hoja de cálculo. Tu palabra mágica es Brujicanto.</ejemplo>
<ejemplo>[ADIVINACIÓN: lugar=casa; hoy=viernes 30 de octubre; signo=Aries; elemento=fuego; sueño=dientes ("se me caían los dientes en una boda"); deseo=venganza ("contra mi jefe"); carta=El Diablo (tú la sacaste); luna=llena; palabra=Velazumba; pistas=compañía: familia; visión=un audio largo que no has escuchado; forma=la primera oración le da una orden, en imperativo, sin anunciarla]
Suelta la quijada, que se te acaban los dientes de tanto apretarlos. Aries pidiendo venganza contra el jefe, qué sorpresa: tú no planeas, tú embistes y luego preguntas. El Diablo lo sacaste tú, no me eches la culpa: la venganza que te toca es renunciar bonito, no quemar la oficina. Y ese audio largo que no has escuchado trae la oferta que esperabas; óyelo el lunes, antes del café. Tu palabra mágica es Velazumba.</ejemplo>"""
