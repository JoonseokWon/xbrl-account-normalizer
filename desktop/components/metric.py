from .card import Card
from .text import label

class MetricCard(Card):
    def __init__(self,title,description,value='—'):
        super().__init__()
        self.body.setSpacing(9)
        self.body.addWidget(label(title,'Muted'))
        self.value=label(value,'MetricValue')
        self.body.addWidget(self.value)
        self.body.addWidget(label(description,'Muted',True))
    def update_value(self,value):
        self.value.setText(f'{value:,}' if isinstance(value,int) else str(value))
