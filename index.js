const express = require('express');
const bodyParser = require('body-parser');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware para entender JSON
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// Rota para o webhook
app.post('/webhook', (req, res) => {
    const incomingMessage = req.body.text || '';

    console.log('Mensagem recebida:', incomingMessage);

    // Resposta padrão
    const response = {
        "type": "text",
        "text": `Você enviou: ${incomingMessage}`
    };

    res.json(response);
});

// Rota de teste
app.get('/', (req, res) => {
    res.send('Servidor funcionando!');
});

// Inicia o servidor
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
