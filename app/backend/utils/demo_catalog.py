"""Synthetic, manually verified learning materials for the private demo workspace."""
from utils.worksheet import validate_worksheet


def sheets():
    samples = [
        ('fractions', 'Дроби и проценты', 'math', '6', [
            (r'Вычислите $\frac{2}{5}+\frac{7}{10}$.', r'$\frac{11}{10}$'),
            (r'Найдите 25% от $80$.', '$20$'),
            (r'Вычислите $\frac{3}{4}\cdot\frac{8}{9}$.', r'$\frac{2}{3}$'),
            (r'В классе $30$ учеников. $\frac{2}{5}$ класса участвуют в олимпиаде. Сколько это учеников?', '$12$')]),
        ('equations', 'Линейные уравнения', 'math', '7', [
            (r'Решите уравнение $3x+5=20$.', '$5$'),
            (r'Решите уравнение $2(x-3)=10$.', '$8$'),
            (r'Решите уравнение $\frac{x}{4}+2=5$.', '$12$'),
            (r'Периметр прямоугольника $30\,\text{см}$. Длина на $3\,\text{см}$ больше ширины. Найдите ширину.', r'$6\,\text{см}$')]),
        ('physics', 'Скорость, сила и плотность', 'physics', '7', [
            (r'Автомобиль проехал $120\,\text{км}$ за $2\,\text{ч}$. Найдите среднюю скорость.', r'$60\,\text{км/ч}$'),
            (r'Тело массой $2\,\text{кг}$ движется с ускорением $3\,\text{м/с}^{2}$. Найдите силу $F=ma$.', r'$6\,\text{Н}$'),
            (r'Масса образца $540\,\text{г}$, объём $200\,\text{см}^{3}$. Найдите плотность.', r'$2{,}7\,\text{г/см}^{3}$')]),
    ]
    return {key: validate_worksheet(dict(schema_version=1, title=title, subject=subject,
                grade=grade, teacher_name='Демонстрационный материал',
                tasks=[dict(id=str(i), question=q, answer=a, note='') for i,(q,a) in enumerate(tasks,1)],
                settings=dict(columns=1,tasks_per_page=len(tasks),template='cards',field='grid',field_height_mm=18)))
            for key,title,subject,grade,tasks in samples}


ANSWERS = {'fractions': ['11/10','20','2/3','12'],
           'equations': ['5','8','12','6 см'],
           'physics': ['60 км/ч','6 Н','2,7 г/см³']}
