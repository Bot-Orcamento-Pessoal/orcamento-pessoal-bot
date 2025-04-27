const express = require('express');
const bodyParser = require('body-parser');

const app = express();
app.use(bodyParser.json());

// Rota para teste
app.get('/', (req, res) => {
    res.send('Bot Orcamento Pessoal está rodando!');
});

// Ouvindo na porta que o Render indicar
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
