const express = require('express');
const bodyParser = require('body-parser');

const app = express();
app.use(bodyParser.json());

// Rota para teste
app.get('/', (req, res) => {
    res.send('Bot Orcamento Pessoal está rodando!');
});

// Rota para receber mensagens do Gupshup
app.post('/webhook', (req, res) => {
    const incomingMessage = req.body;

    console.log('Mensagem recebida:', incomingMessage);

    // Aqui você pode responder ou processar a mensagem recebida
    res.sendStatus(200); // Responde para o Gupshup que recebeu
});

// Ouvindo na porta que o Render indicar
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
